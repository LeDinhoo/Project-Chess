from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import chess
import chess.engine
import chess.pgn


ROOT = Path(__file__).resolve().parent.parent
SUPPORTED_THEMES = {"mate", "fork", "hangingPiece", "pin", "discoveredAttack"}
SRS_INTERVALS = (3, 7, 14, 30, 30)
PUZZLE_RATING_WINDOW = 400
PUZZLE_CANDIDATE_LIMIT = 20
PUZZLE_BATCH_SIZE = 50


class SyncError(RuntimeError):
    pass


def is_eligible_time_control(value: str | None) -> bool:
    if not value or "+" not in value:
        return False
    base, increment = value.split("+", 1)
    try:
        return int(base) == 900 and int(increment) == 10
    except ValueError:
        return False


def _config(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid config.json: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("config.json must contain an object")

    username = data.get("chesscom_username")
    stockfish_path = data.get("stockfish_path")
    initial_games = data.get("initial_games", 20)
    if not isinstance(username, str) or not username.strip():
        raise ValueError("chesscom_username must be a non-empty string")
    if not isinstance(stockfish_path, str) or not stockfish_path.strip():
        raise ValueError("stockfish_path must be a non-empty string")
    if isinstance(initial_games, bool) or not isinstance(initial_games, int) or initial_games < 1:
        raise ValueError("initial_games must be a positive integer")
    return {
        "chesscom_username": username.strip(),
        "stockfish_path": stockfish_path.strip(),
        "initial_games": initial_games,
    }


def _request_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "chess-trainer/0.1"})
    with urlopen(request, timeout=20) as response:
        return response.read()


def _archive_urls(username: str) -> list[str]:
    url = f"https://api.chess.com/pub/player/{quote(username, safe='')}/games/archives"
    try:
        payload = json.loads(_request_bytes(url).decode("utf-8"))
    except (OSError, URLError, UnicodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"Chess.com is unavailable: {exc}") from exc

    archives = payload.get("archives") if isinstance(payload, dict) else None
    if not isinstance(archives, list):
        raise SyncError("Chess.com returned no archive list")
    valid = []
    for archive in archives:
        parsed = urlparse(archive) if isinstance(archive, str) else None
        if parsed and parsed.scheme == "https" and parsed.hostname == "api.chess.com":
            valid.append(archive)
    return valid


def _pgn_games(text: str) -> Iterable[chess.pgn.Game]:
    stream = io.StringIO(text)
    while game := chess.pgn.read_game(stream):
        yield game


def _time_control(headers: chess.pgn.Headers) -> str | None:
    return headers.get("TimeControl")


def _user_color(headers: chess.pgn.Headers, username: str) -> chess.Color | None:
    username = username.casefold()
    white = headers.get("White", "").casefold()
    black = headers.get("Black", "").casefold()
    if white == username and black != username:
        return chess.WHITE
    if black == username and white != username:
        return chess.BLACK
    return None


def _rating(headers: chess.pgn.Headers, color: chess.Color | None) -> int | None:
    if color is None:
        return None
    value = headers.get("WhiteElo" if color else "BlackElo", "")
    match = re.match(r"\d+", value)
    return int(match.group()) if match else None


def _game_id(game: chess.pgn.Game) -> str:
    link = game.headers.get("Link") or game.headers.get("GameId")
    if link:
        return link.rstrip("/").rsplit("/", 1)[-1]
    return hashlib.sha256(str(game).encode("utf-8")).hexdigest()


def _played_at(game: chess.pgn.Game) -> str | None:
    value = game.headers.get("Date") or game.headers.get("EndDate")
    return value.replace(".", "-") if value else None


def _has_mate_in_one(board: chess.Board) -> bool:
    for move in list(board.legal_moves):
        board.push(move)
        mate = board.is_checkmate()
        board.pop()
        if mate:
            return True
    return False


def _creates_fork(board: chess.Board, move: chess.Move, victim_color: chess.Color) -> bool:
    targets = []
    for square in board.attacks(move.to_square):
        piece = board.piece_at(square)
        if piece and piece.color == victim_color and piece.piece_type != chess.PAWN:
            targets.append(piece)
    return len(targets) >= 2 and any(piece.piece_type in {chess.QUEEN, chess.ROOK, chess.KING} for piece in targets)


def _creates_pin(before: chess.Board, after: chess.Board, victim_color: chess.Color) -> bool:
    for square, piece in after.piece_map().items():
        if (
            piece.color == victim_color
            and piece.piece_type != chess.KING
            and after.is_pinned(victim_color, square)
            and not before.is_pinned(victim_color, square)
        ):
            return True
    return False


def _creates_discovered_attack(
    before: chess.Board,
    after: chess.Board,
    move: chess.Move,
    victim_color: chess.Color,
) -> bool:
    attacker_color = not victim_color
    for target, piece in after.piece_map().items():
        if piece.color != victim_color or piece.piece_type == chess.PAWN:
            continue
        old_attackers = set(before.attackers(attacker_color, target))
        new_attackers = set(after.attackers(attacker_color, target)) - old_attackers
        if any(chess.BB_SQUARES[move.from_square] & chess.between(attacker, target) for attacker in new_attackers):
            return True
    return False


def classify_tactical_mistake(
    before: chess.Board,
    after: chess.Board,
    best_move: chess.Move | None,
    best_response: chess.Move | None,
) -> str | None:
    victim_color = before.turn
    if _has_mate_in_one(after):
        return "mate"

    if best_move and best_move in before.legal_moves:
        best_board = before.copy()
        best_board.push(best_move)
        if best_board.is_checkmate():
            return "mate"

    if not best_response or best_response not in after.legal_moves:
        return None

    response_board = after.copy()
    captured = response_board.piece_at(best_response.to_square)
    response_board.push(best_response)

    if _creates_fork(response_board, best_response, victim_color):
        return "fork"
    if (
        captured
        and captured.color == victim_color
        and captured.piece_type != chess.PAWN
        and not any(move.to_square == best_response.to_square for move in response_board.legal_moves)
    ):
        return "hangingPiece"
    if _creates_pin(after, response_board, victim_color):
        return "pin"
    if _creates_discovered_attack(after, response_board, best_response, victim_color):
        return "discoveredAttack"
    return None


def _analyze_game(
    game: chess.pgn.Game,
    user_color: chess.Color,
    engine: chess.engine.SimpleEngine,
) -> list[tuple[int, str, str, int]]:
    board = game.board()
    mistakes = []
    limit = chess.engine.Limit(depth=12)
    for ply, move in enumerate(game.mainline_moves()):
        if board.turn != user_color:
            board.push(move)
            continue

        before = board.copy()
        before_info = engine.analyse(board, limit)
        best_move = (before_info.get("pv") or [None])[0]
        board.push(move)
        after_info = engine.analyse(board, limit)
        before_score = before_info["score"].pov(user_color).score(mate_score=100000)
        after_score = after_info["score"].pov(user_color).score(mate_score=100000)
        loss = before_score - after_score
        if loss >= 150:
            response = (after_info.get("pv") or [None])[0]
            theme = classify_tactical_mistake(before, board, best_move, response)
            if theme:
                mistakes.append((ply, before.fen(), theme, loss))
    return mistakes


class Core:
    def __init__(
        self,
        config_path: Path = ROOT / "config.json",
        app_db_path: Path = ROOT / "app.db",
        puzzle_db_path: Path = ROOT / "puzzles.db",
    ) -> None:
        self.config_path = Path(config_path)
        self.app_db_path = Path(app_db_path)
        self.puzzle_db_path = Path(puzzle_db_path)
        self.initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.app_db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        except:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        self.app_db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS games (
                    game_id TEXT PRIMARY KEY,
                    pgn TEXT NOT NULL,
                    played_at TEXT,
                    white TEXT NOT NULL,
                    black TEXT NOT NULL,
                    result TEXT NOT NULL,
                    time_control TEXT NOT NULL,
                    user_rating INTEGER
                );
                CREATE TABLE IF NOT EXISTS mistakes (
                    id INTEGER PRIMARY KEY,
                    game_id TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
                    ply INTEGER NOT NULL,
                    fen TEXT NOT NULL,
                    theme TEXT NOT NULL,
                    loss_cp INTEGER NOT NULL,
                    UNIQUE(game_id, ply)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_date TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS session_puzzles (
                    session_date TEXT NOT NULL REFERENCES sessions(session_date) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    puzzle_id TEXT NOT NULL,
                    result TEXT CHECK(result IN ('success', 'failed') OR result IS NULL),
                    elapsed_ms INTEGER,
                    PRIMARY KEY(session_date, position)
                );
                CREATE TABLE IF NOT EXISTS puzzle_progress (
                    puzzle_id TEXT PRIMARY KEY,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    due_date TEXT NOT NULL,
                    last_result TEXT CHECK(last_result IN ('success', 'failed') OR last_result IS NULL),
                    last_elapsed_ms INTEGER
                );
                """
            )

    def sync(self) -> dict[str, int]:
        config = _config(self.config_path)
        with self._connect() as connection:
            stored_games = connection.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        target = config["initial_games"] if stored_games == 0 else 10

        archives = _archive_urls(config["chesscom_username"])
        candidates: list[chess.pgn.Game] = []
        try:
            for archive in reversed(archives):
                text = _request_bytes(archive + "/pgn").decode("utf-8", errors="replace")
                archive_games = list(_pgn_games(text))
                for game in reversed(archive_games):
                    if is_eligible_time_control(_time_control(game.headers)):
                        candidates.append(game)
                        if len(candidates) >= target:
                            break
                if len(candidates) >= target:
                    break
        except (OSError, URLError, UnicodeError) as exc:
            raise SyncError(f"Chess.com is unavailable: {exc}") from exc

        new_games = []
        seen_ids = set()
        with self._connect() as connection:
            for game in candidates:
                game_id = _game_id(game)
                if game_id in seen_ids or connection.execute(
                    "SELECT 1 FROM games WHERE game_id = ?", (game_id,)
                ).fetchone():
                    continue
                seen_ids.add(game_id)
                new_games.append((game_id, game))

        analyzed: list[tuple[str, chess.pgn.Game, list[tuple[int, str, str, int]]]] = []
        if new_games:
            stockfish_path = Path(config["stockfish_path"])
            if not stockfish_path.is_file():
                raise SyncError(f"Stockfish executable not found: {stockfish_path}")
            try:
                engine = chess.engine.SimpleEngine.popen_uci(str(stockfish_path))
                try:
                    for game_id, game in new_games:
                        user_color = _user_color(game.headers, config["chesscom_username"])
                        mistakes = (
                            _analyze_game(game, user_color, engine) if user_color is not None else []
                        )
                        analyzed.append((game_id, game, mistakes))
                finally:
                    engine.quit()
            except Exception as exc:
                raise SyncError(f"Stockfish analysis failed: {exc}") from exc

        with self._connect() as connection:
            for game_id, game, mistakes in analyzed:
                headers = game.headers
                user_color = _user_color(headers, config["chesscom_username"])
                connection.execute(
                    "INSERT INTO games "
                    "(game_id, pgn, played_at, white, black, result, time_control, user_rating) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        game_id,
                        str(game),
                        _played_at(game),
                        headers.get("White", ""),
                        headers.get("Black", ""),
                        headers.get("Result", "*"),
                        headers.get("TimeControl", ""),
                        _rating(headers, user_color),
                    ),
                )
                connection.executemany(
                    "INSERT OR IGNORE INTO mistakes "
                    "(game_id, ply, fen, theme, loss_cp) VALUES (?, ?, ?, ?, ?)",
                    [(game_id, ply, fen, theme, loss) for ply, fen, theme, loss in mistakes],
                )

        return {"eligible": len(candidates), "imported": len(analyzed), "mistakes": sum(len(item[2]) for item in analyzed)}

    def _weaknesses(self, connection: sqlite3.Connection) -> list[str]:
        rows = connection.execute(
            "SELECT theme, COUNT(*) AS count FROM mistakes "
            "GROUP BY theme ORDER BY count DESC, theme"
        ).fetchall()
        return [row["theme"] for row in rows if row["theme"] in SUPPORTED_THEMES]

    def _rating_target(self, connection: sqlite3.Connection) -> int:
        value = connection.execute("SELECT AVG(user_rating) FROM games WHERE user_rating IS NOT NULL").fetchone()[0]
        return round(value) if value is not None else 1200

    def _puzzle_connection(self) -> sqlite3.Connection | None:
        if not self.puzzle_db_path.is_file():
            return None
        uri = f"file:{self.puzzle_db_path.resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def _select_puzzles(self, connection: sqlite3.Connection, session_date: str) -> list[sqlite3.Row]:
        puzzle_connection = self._puzzle_connection()
        if puzzle_connection is None:
            return []
        try:
            known_ids = {
                row["puzzle_id"]
                for row in connection.execute(
                    "SELECT puzzle_id FROM puzzle_progress UNION SELECT puzzle_id FROM session_puzzles"
                )
            }
            recent_ids = {
                row["puzzle_id"]
                for row in connection.execute(
                    "SELECT puzzle_id FROM session_puzzles WHERE session_date < ? "
                    "ORDER BY session_date DESC, position LIMIT 20",
                    (session_date,),
                )
            }
            selected: list[sqlite3.Row] = []
            selected_ids: set[str] = set()

            def add(row: sqlite3.Row | None) -> None:
                if row is not None and row["puzzle_id"] not in selected_ids:
                    selected.append(row)
                    selected_ids.add(row["puzzle_id"])

            def puzzle_by_id(puzzle_id: str) -> sqlite3.Row | None:
                return puzzle_connection.execute(
                    "SELECT puzzle_id, fen, moves, rating, themes FROM puzzles WHERE puzzle_id = ?",
                    (puzzle_id,),
                ).fetchone()

            remaining = PUZZLE_CANDIDATE_LIMIT
            unfinished_ids = [
                row["puzzle_id"]
                for row in connection.execute(
                    "SELECT puzzle_id FROM session_puzzles "
                    "WHERE session_date < ? AND result IS NULL "
                    "GROUP BY puzzle_id ORDER BY MIN(session_date), MIN(position) LIMIT ?",
                    (session_date, remaining),
                )
            ]
            for puzzle_id in unfinished_ids:
                add(puzzle_by_id(puzzle_id))
                if len(selected) == PUZZLE_CANDIDATE_LIMIT:
                    return selected

            due_ids = [
                row["puzzle_id"]
                for row in connection.execute(
                    "SELECT puzzle_id FROM puzzle_progress WHERE due_date <= ? "
                    "ORDER BY due_date, puzzle_id",
                    (session_date,),
                )
            ]
            for puzzle_id in due_ids:
                add(puzzle_by_id(puzzle_id))
                if len(selected) == PUZZLE_CANDIDATE_LIMIT:
                    return selected

            weaknesses = self._weaknesses(connection)
            target_rating = self._rating_target(connection)
            rating_min = target_rating - PUZZLE_RATING_WINDOW
            rating_max = target_rating + PUZZLE_RATING_WINDOW
            for theme in weaknesses:
                offset = 0
                while len(selected) < PUZZLE_CANDIDATE_LIMIT:
                    rows = puzzle_connection.execute(
                        "SELECT puzzle_id, fen, moves, rating, themes FROM puzzles "
                        "WHERE ' ' || themes || ' ' LIKE ? AND rating BETWEEN ? AND ? "
                        "ORDER BY ABS(rating - ?), puzzle_id LIMIT ? OFFSET ?",
                        (f"% {theme} %", rating_min, rating_max, target_rating, PUZZLE_BATCH_SIZE, offset),
                    ).fetchall()
                    if not rows:
                        break
                    offset += len(rows)
                    for row in rows:
                        if row["puzzle_id"] not in known_ids and row["puzzle_id"] not in recent_ids:
                            add(row)
                            if len(selected) == PUZZLE_CANDIDATE_LIMIT:
                                return selected
                    if len(rows) < PUZZLE_BATCH_SIZE:
                        break

            for theme in weaknesses:
                offset = 0
                while len(selected) < PUZZLE_CANDIDATE_LIMIT:
                    rows = puzzle_connection.execute(
                        "SELECT puzzle_id, fen, moves, rating, themes FROM puzzles "
                        "WHERE ' ' || themes || ' ' LIKE ? AND rating BETWEEN ? AND ? "
                        "ORDER BY ABS(rating - ?), puzzle_id LIMIT ? OFFSET ?",
                        (f"% {theme} %", rating_min, rating_max, target_rating, PUZZLE_BATCH_SIZE, offset),
                    ).fetchall()
                    if not rows:
                        break
                    offset += len(rows)
                    for row in rows:
                        if row["puzzle_id"] in known_ids:
                            add(row)
                            if len(selected) == PUZZLE_CANDIDATE_LIMIT:
                                return selected
                    if len(rows) < PUZZLE_BATCH_SIZE:
                        break
            return selected
        finally:
            puzzle_connection.close()

    def _session_payload(self, connection: sqlite3.Connection, session_date: str) -> dict[str, Any] | None:
        rows = connection.execute(
            "SELECT position, puzzle_id, result, elapsed_ms FROM session_puzzles "
            "WHERE session_date = ? ORDER BY position",
            (session_date,),
        ).fetchall()
        if not rows:
            return None
        puzzle_connection = self._puzzle_connection()
        if puzzle_connection is None:
            raise RuntimeError("puzzles.db is missing")
        try:
            puzzles = []
            for row in rows:
                puzzle = puzzle_connection.execute(
                    "SELECT puzzle_id, fen, moves, rating, themes FROM puzzles WHERE puzzle_id = ?",
                    (row["puzzle_id"],),
                ).fetchone()
                if puzzle is None:
                    raise RuntimeError(f"puzzle not found: {row['puzzle_id']}")
                try:
                    board = chess.Board(puzzle["fen"])
                    moves = (puzzle["moves"] or "").split()
                    if len(moves) < 2:
                        raise ValueError("expected at least two moves")
                    setup_move = chess.Move.from_uci(moves[0])
                    if not board.is_legal(setup_move):
                        raise ValueError(f"illegal move: {moves[0]}")
                    board.push(setup_move)
                    display_fen = board.fen()
                    legal_moves = []
                    for index, token in enumerate(moves[1:], 1):
                        move = chess.Move.from_uci(token)
                        if index % 2 == 1:
                            legal_moves.append([legal.uci() for legal in board.legal_moves])
                        if not board.is_legal(move):
                            raise ValueError(f"illegal move: {token}")
                        board.push(move)
                except (AttributeError, IndexError, TypeError, ValueError) as exc:
                    raise RuntimeError(
                        f"invalid puzzle data for {puzzle['puzzle_id']}: {exc}"
                    ) from exc
                puzzles.append(
                    {
                        "position": row["position"],
                        "puzzle_id": puzzle["puzzle_id"],
                        "fen": display_fen,
                        "moves": " ".join(moves[1:]),
                        "last_move": moves[0],
                        "legal_moves": legal_moves,
                        "rating": puzzle["rating"],
                        "themes": puzzle["themes"],
                        "result": row["result"],
                        "elapsed_ms": row["elapsed_ms"],
                    }
                )
            return {
                "date": session_date,
                "puzzles": puzzles,
                "completed": sum(puzzle["result"] is not None for puzzle in puzzles),
            }
        finally:
            puzzle_connection.close()

    def start_session(self, session_date: str | None = None) -> dict[str, Any]:
        session_date = _valid_date(session_date)
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM sessions WHERE session_date = ?", (session_date,)
            ).fetchone():
                payload = self._session_payload(connection, session_date)
                if payload is not None:
                    return payload

            selected = self._select_puzzles(connection, session_date)
            if len(selected) < 20:
                raise RuntimeError("fewer than 20 matching puzzles are available")
            connection.execute(
                "INSERT INTO sessions(session_date, created_at) VALUES (?, ?)",
                (session_date, date.today().isoformat()),
            )
            connection.executemany(
                "INSERT INTO session_puzzles(session_date, position, puzzle_id) VALUES (?, ?, ?)",
                [(session_date, position, row["puzzle_id"]) for position, row in enumerate(selected, 1)],
            )
            return self._session_payload(connection, session_date)  # type: ignore[return-value]

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return [
                {
                    "date": row["session_date"],
                    "completed": row["completed"],
                    "total": row["total"],
                }
                for row in connection.execute(
                    "SELECT session_date, "
                    "SUM(result IS NOT NULL) AS completed, COUNT(*) AS total "
                    "FROM session_puzzles GROUP BY session_date ORDER BY session_date DESC"
                )
            ]

    def get_session(self, session_date: str) -> dict[str, Any] | None:
        session_date = _valid_date(session_date)
        with self._connect() as connection:
            return self._session_payload(connection, session_date)

    def record_result(
        self,
        session_date: str,
        position: int,
        success: bool,
        elapsed_ms: int | float,
    ) -> dict[str, Any]:
        session_date = _valid_date(session_date)
        if not isinstance(position, int) or position < 1:
            raise ValueError("position must be a positive integer")
        if not isinstance(success, bool):
            raise ValueError("success must be a boolean")
        try:
            elapsed_ms = int(round(float(elapsed_ms)))
        except (TypeError, ValueError) as exc:
            raise ValueError("elapsed_ms must be numeric") from exc
        if elapsed_ms < 0:
            raise ValueError("elapsed_ms must not be negative")

        with self._connect() as connection:
            row = connection.execute(
                "SELECT puzzle_id, result, elapsed_ms FROM session_puzzles "
                "WHERE session_date = ? AND position = ?",
                (session_date, position),
            ).fetchone()
            if row is None:
                raise ValueError("session puzzle does not exist")
            if row["result"] is not None:
                return {
                    "date": session_date,
                    "position": position,
                    "result": row["result"],
                    "elapsed_ms": row["elapsed_ms"],
                }

            result = "success" if success else "failed"
            connection.execute(
                "UPDATE session_puzzles SET result = ?, elapsed_ms = ? "
                "WHERE session_date = ? AND position = ?",
                (result, elapsed_ms, session_date, position),
            )
            if success:
                current = connection.execute(
                    "SELECT success_count FROM puzzle_progress WHERE puzzle_id = ?",
                    (row["puzzle_id"],),
                ).fetchone()
                count = current["success_count"] if current else 0
                due = date.today() + timedelta(days=SRS_INTERVALS[min(count, len(SRS_INTERVALS) - 1)])
                connection.execute(
                    "INSERT INTO puzzle_progress "
                    "(puzzle_id, success_count, due_date, last_result, last_elapsed_ms) "
                    "VALUES (?, ?, ?, 'success', ?) "
                    "ON CONFLICT(puzzle_id) DO UPDATE SET success_count = excluded.success_count, "
                    "due_date = excluded.due_date, last_result = excluded.last_result, "
                    "last_elapsed_ms = excluded.last_elapsed_ms",
                    (row["puzzle_id"], min(count + 1, len(SRS_INTERVALS)), due.isoformat(), elapsed_ms),
                )
            else:
                due = date.today() + timedelta(days=1)
                connection.execute(
                    "INSERT INTO puzzle_progress "
                    "(puzzle_id, success_count, due_date, last_result, last_elapsed_ms) "
                    "VALUES (?, 0, ?, 'failed', ?) "
                    "ON CONFLICT(puzzle_id) DO UPDATE SET success_count = 0, due_date = excluded.due_date, "
                    "last_result = excluded.last_result, last_elapsed_ms = excluded.last_elapsed_ms",
                    (row["puzzle_id"], due.isoformat(), elapsed_ms),
                )
            return {
                "date": session_date,
                "position": position,
                "result": result,
                "elapsed_ms": elapsed_ms,
            }


def _valid_date(value: str | None) -> str:
    value = value or date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("date must be YYYY-MM-DD") from exc
