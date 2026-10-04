import csv
import io
import json
import sqlite3
import tempfile
from contextlib import closing
from datetime import date as real_date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch

import chess
import compression.zstd as zstd

from backend.core import Core, classify_tactical_mistake, is_eligible_time_control
from backend.import_puzzles import import_puzzles


class CoreTests(TestCase):
    puzzle_fen = chess.STARTING_FEN
    puzzle_moves = "e2e4 e7e5 g1f3"

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        self.config_path = root / "config.json"
        self.app_db_path = root / "app.db"
        self.puzzle_db_path = root / "puzzles.db"
        stockfish_path = root / "stockfish.exe"
        stockfish_path.write_text("", encoding="utf-8")
        self.config_path.write_text(
            json.dumps(
                {
                    "chesscom_username": "alice",
                    "stockfish_path": str(stockfish_path),
                    "initial_games": 1,
                }
            ),
            encoding="utf-8",
        )
        self._create_puzzle_db()
        self.core = Core(self.config_path, self.app_db_path, self.puzzle_db_path)

    def _create_puzzle_db(self):
        with closing(sqlite3.connect(self.puzzle_db_path)) as connection:
            connection.execute(
                "CREATE TABLE puzzles ("
                "puzzle_id TEXT PRIMARY KEY, fen TEXT NOT NULL, moves TEXT NOT NULL, "
                "rating INTEGER NOT NULL, themes TEXT NOT NULL)"
            )
            connection.commit()

    def _add_puzzles(self, puzzle_ids, fen=None, moves=None, rating=1200, themes="fork"):
        with closing(sqlite3.connect(self.puzzle_db_path)) as connection:
            connection.executemany(
                "INSERT INTO puzzles(puzzle_id, fen, moves, rating, themes) VALUES (?, ?, ?, ?, ?)",
                [
                    (puzzle_id, fen or self.puzzle_fen, moves or self.puzzle_moves, rating, themes)
                    for puzzle_id in puzzle_ids
                ],
            )
            connection.commit()

    def _add_weakness(self, theme="fork", rating=1200):
        with self.core._connect() as connection:
            connection.execute(
                "INSERT INTO games(game_id, pgn, white, black, result, time_control, user_rating) "
                "VALUES ('game-1', '', 'alice', 'bob', '*', '900+10', ?)",
                (rating,),
            )
            connection.execute(
                "INSERT INTO mistakes(game_id, ply, fen, theme, loss_cp) "
                "VALUES ('game-1', 1, ?, ?, 150)",
                (self.puzzle_fen, theme),
            )

    def _add_session(self, session_date, puzzle_ids):
        with self.core._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO sessions(session_date, created_at) VALUES (?, ?)",
                (session_date, session_date),
            )
            session_id = cursor.lastrowid
            connection.executemany(
                "INSERT INTO session_puzzles(session_id, position, puzzle_id) VALUES (?, ?, ?)",
                [(session_id, position, puzzle_id) for position, puzzle_id in enumerate(puzzle_ids, 1)],
            )
            return session_id

    def _add_progress(self, puzzle_id, due_date, success_count=0, result="success"):
        with self.core._connect() as connection:
            connection.execute(
                "INSERT INTO puzzle_progress"
                "(puzzle_id, success_count, due_date, last_result) VALUES (?, ?, ?, ?)",
                (puzzle_id, success_count, due_date, result),
            )

    def test_exact_15_plus_10_filter(self):
        for value in ("900+10",):
            with self.subTest(value=value):
                self.assertTrue(is_eligible_time_control(value))
        for value in ("900+0", "900+5", "600+10", "900", "900+ten", "", None):
            with self.subTest(value=value):
                self.assertFalse(is_eligible_time_control(value))

    def test_sync_does_not_persist_duplicate_game(self):
        pgn = """[Event "test"]
[White "alice"]
[Black "bob"]
[Result "1/2-1/2"]
[TimeControl "900+10"]
[Date "2026.01.01"]
[Link "https://www.chess.com/game/live/duplicate"]

"""
        with (
            patch("backend.core._archive_urls", return_value=["https://api.chess.com/pub/archive"]),
            patch("backend.core._request_bytes", return_value=pgn.encode()),
            patch("backend.core.chess.engine.SimpleEngine.popen_uci") as popen,
        ):
            self.assertEqual(self.core.sync()["imported"], 1)
            self.assertEqual(self.core.sync()["imported"], 0)
            popen.assert_called_once()
        with self.core._connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM games").fetchone()[0], 1)

    def test_import_skips_invalid_later_move_and_continues(self):
        source = Path(self.tempdir.name) / "puzzles.csv.zst"
        database = Path(self.tempdir.name) / "imported-puzzles.db"
        fen = chess.STARTING_FEN
        rows = (
            ("valid-before", fen, "e2e4 e7e5 g1f3", "1200", "fork"),
            ("invalid-later", fen, "e2e4 e7e5 e2e3", "1200", "fork"),
            ("valid-after", fen, "d2d4 d7d5 c2c4", "1200", "fork"),
        )
        csv_text = io.StringIO(newline="")
        writer = csv.writer(csv_text)
        writer.writerow(("PuzzleId", "FEN", "Moves", "Rating", "Themes"))
        writer.writerows(rows)
        with zstd.open(source, "wt", encoding="utf-8", newline="") as stream:
            stream.write(csv_text.getvalue())

        self.assertEqual(import_puzzles(source, database), 2)
        with closing(sqlite3.connect(database)) as connection:
            imported = connection.execute(
                "SELECT puzzle_id, fen, moves FROM puzzles ORDER BY puzzle_id"
            ).fetchall()
        self.assertEqual(
            imported,
            [
                ("valid-after", fen, "d2d4 d7d5 c2c4"),
                ("valid-before", fen, "e2e4 e7e5 g1f3"),
            ],
        )

    def test_supported_tactical_classification_and_uncertain_position(self):
        cases = (
            (
                "mate",
                "7k/5Q2/6K1/8/8/8/8/8 w - - 0 1",
                "f7f6",
                "f7f8",
                None,
            ),
            (
                "fork",
                "k7/8/8/8/8/P6n/8/3K3R w - - 0 1",
                "a3a4",
                None,
                "h3f2",
            ),
            (
                "hangingPiece",
                "r6k/8/8/8/8/8/1P6/R6K w - - 0 1",
                "b2b3",
                None,
                "a8a1",
            ),
            (
                "pin",
                "k7/8/8/7q/8/P7/4R3/4K3 w - - 0 1",
                "a3a4",
                None,
                "h5e8",
            ),
            (
                "discoveredAttack",
                "k3r3/8/8/8/4n3/8/P7/4Q2K w - - 0 1",
                "a2a3",
                None,
                "e4f2",
            ),
            (
                None,
                "k7/8/8/8/8/8/P7/4K3 w - - 0 1",
                "a2a3",
                None,
                "a8b8",
            ),
        )
        for expected, fen, played_uci, best_uci, response_uci in cases:
            with self.subTest(expected=expected):
                before = chess.Board(fen)
                after = before.copy()
                after.push_uci(played_uci)
                best_move = chess.Move.from_uci(best_uci) if best_uci else None
                response = chess.Move.from_uci(response_uci) if response_uci else None
                self.assertEqual(
                    classify_tactical_mistake(before, after, best_move, response), expected
                )

    def test_same_day_session_is_frozen_and_has_20_unique_puzzles(self):
        puzzle_ids = [f"puzzle-{number:02d}" for number in range(20)]
        self._add_puzzles(puzzle_ids)
        self._add_weakness()
        first = self.core.start_session("2026-01-01")
        second = self.core.start_session("2026-01-01")
        self.assertEqual(first["session_id"], second["session_id"])
        first_ids = [puzzle["puzzle_id"] for puzzle in first["puzzles"]]
        second_ids = [puzzle["puzzle_id"] for puzzle in second["puzzles"]]
        self.assertEqual(len(first_ids), 20)
        self.assertEqual(len(set(first_ids)), 20)
        self.assertEqual(second_ids, first_ids)

    def test_unfinished_puzzle_carries_forward_without_changing_history(self):
        puzzle_ids = [f"puzzle-{number:02d}" for number in range(20)]
        self._add_puzzles(puzzle_ids)
        old_session_id = self._add_session("2026-01-01", [puzzle_ids[0]])
        self._add_weakness()
        later = self.core.start_session("2026-01-02")
        later_ids = [puzzle["puzzle_id"] for puzzle in later["puzzles"]]
        self.assertEqual(later_ids[0], puzzle_ids[0])
        self.assertEqual(len(set(later_ids)), 20)
        with self.core._connect() as connection:
            old = connection.execute(
                "SELECT puzzle_id, result FROM session_puzzles WHERE session_id = ?", (old_session_id,)
            ).fetchone()
        self.assertEqual((old["puzzle_id"], old["result"]), (puzzle_ids[0], None))

    def test_latest_occurrence_controls_unfinished_carry_over(self):
        carry_over_ids = ["puzzle-a", "puzzle-b", "puzzle-c", "puzzle-d"]
        filler_ids = [f"filler-{number:02d}" for number in range(19)]
        self._add_puzzles(carry_over_ids, themes="other")
        self._add_puzzles(filler_ids)
        occurrences = (
            ("2026-01-01", "puzzle-a", None),
            ("2026-01-02", "puzzle-a", "success"),
            ("2026-01-02", "puzzle-c", None),
            ("2026-01-02", "puzzle-c", "success"),
            ("2026-01-03", "puzzle-b", "success"),
            ("2026-01-04", "puzzle-b", None),
            ("2026-01-05", "puzzle-d", None),
        )
        for session_date, puzzle_id, result in occurrences:
            session_id = self._add_session(session_date, [puzzle_id])
            if result is not None:
                with self.core._connect() as connection:
                    connection.execute(
                        "UPDATE session_puzzles SET result = ? WHERE session_id = ? AND position = 1",
                        (result, session_id),
                    )

        self._add_weakness()
        with self.core._connect() as connection:
            selected_ids = [
                row["puzzle_id"] for row in self.core._select_puzzles(connection, "2026-01-05")
            ]

        self.assertEqual(selected_ids[0], "puzzle-b")
        self.assertIn("puzzle-b", selected_ids)
        self.assertNotIn("puzzle-a", selected_ids)
        self.assertNotIn("puzzle-c", selected_ids)
        self.assertNotIn("puzzle-d", selected_ids)
        self.assertEqual(len(selected_ids), 20)

    def test_due_puzzles_have_priority_without_overlap(self):
        puzzle_ids = [f"puzzle-{number:02d}" for number in range(20)]
        self._add_puzzles(puzzle_ids)
        self._add_session("2026-01-01", [puzzle_ids[0]])
        self._add_progress(puzzle_ids[0], "2026-01-01")
        self._add_progress(puzzle_ids[1], "2026-01-02")
        self._add_progress(puzzle_ids[2], "2026-01-03")
        self._add_weakness()
        with self.core._connect() as connection:
            selected = self.core._select_puzzles(connection, "2026-01-04")
        selected_ids = [row["puzzle_id"] for row in selected]
        self.assertEqual(selected_ids[:3], puzzle_ids[:3])
        self.assertEqual(len(selected_ids), len(set(selected_ids)))
        self.assertLess(selected_ids.index(puzzle_ids[2]), selected_ids.index(puzzle_ids[3]))

    def test_candidate_scanning_continues_after_unusable_batch(self):
        puzzle_ids = [f"puzzle-{number:02d}" for number in range(70)]
        self._add_puzzles(puzzle_ids)
        for puzzle_id in puzzle_ids[:50]:
            self._add_progress(puzzle_id, "2026-12-31")
        self._add_weakness()
        with self.core._connect() as connection:
            selected = self.core._select_puzzles(connection, "2026-01-01")
        self.assertEqual([row["puzzle_id"] for row in selected], puzzle_ids[50:])

    def test_insufficient_supply_fails_instead_of_duplicating(self):
        self._add_puzzles([f"puzzle-{number:02d}" for number in range(19)])
        self._add_weakness()
        with self.assertRaisesRegex(RuntimeError, "fewer than 20"):
            self.core.start_session("2026-01-01")

    def test_spaced_repetition_schedule_and_failure_reset(self):
        puzzle_id = "puzzle-srs"
        self._add_puzzles([puzzle_id])
        session_dates = [f"2026-01-0{number}" for number in range(1, 8)]
        session_ids = [self._add_session(session_date, [puzzle_id]) for session_date in session_dates]
        fixed_today = real_date(2026, 1, 1)
        fixed_date = SimpleNamespace(today=lambda: fixed_today, fromisoformat=real_date.fromisoformat)
        with patch("backend.core.date", fixed_date):
            for number, interval in enumerate((3, 7, 14, 30, 30)):
                self.core.record_result(session_ids[number], 1, True, 100 + number)
                with self.core._connect() as connection:
                    progress = connection.execute(
                        "SELECT success_count, due_date FROM puzzle_progress WHERE puzzle_id = ?",
                        (puzzle_id,),
                    ).fetchone()
                self.assertEqual(progress["success_count"], min(number + 1, 5))
                self.assertEqual(
                    progress["due_date"], (fixed_today + timedelta(days=interval)).isoformat()
                )

            self.core.record_result(session_ids[5], 1, False, 600)
            with self.core._connect() as connection:
                progress = connection.execute(
                    "SELECT success_count, due_date, last_result FROM puzzle_progress WHERE puzzle_id = ?",
                    (puzzle_id,),
                ).fetchone()
            self.assertEqual(
                (progress["success_count"], progress["due_date"], progress["last_result"]),
                (0, (fixed_today + timedelta(days=1)).isoformat(), "failed"),
            )

            self.core.record_result(session_ids[6], 1, True, 700)
            with self.core._connect() as connection:
                progress = connection.execute(
                    "SELECT success_count, due_date FROM puzzle_progress WHERE puzzle_id = ?",
                    (puzzle_id,),
                ).fetchone()
            self.assertEqual(
                (progress["success_count"], progress["due_date"]),
                (1, (fixed_today + timedelta(days=3)).isoformat()),
            )

    def test_first_result_wins(self):
        puzzle_id = "puzzle-result"
        self._add_puzzles([puzzle_id])
        session_id = self._add_session("2026-01-01", [puzzle_id])
        self.assertEqual(
            self.core.record_result(session_id, 1, False, 321),
            {
                "session_id": session_id,
                "date": "2026-01-01",
                "position": 1,
                "result": "failed",
                "elapsed_ms": 321,
            },
        )
        self.assertEqual(
            self.core.record_result(session_id, 1, True, 999),
            {
                "session_id": session_id,
                "date": "2026-01-01",
                "position": 1,
                "result": "failed",
                "elapsed_ms": 321,
            },
        )
        with self.core._connect() as connection:
            stored = connection.execute(
                "SELECT result, elapsed_ms FROM session_puzzles WHERE session_id = ?", (session_id,)
            ).fetchone()
        self.assertEqual((stored["result"], stored["elapsed_ms"]), ("failed", 321))

    def test_lichess_payload_transformation_and_invalid_data(self):
        puzzle_id = "puzzle-payload"
        fen = chess.STARTING_FEN
        moves = "e2e4 e7e5 g1f3"
        self._add_puzzles([puzzle_id], fen=fen, moves=moves)
        session_id = self._add_session("2026-01-01", [puzzle_id])
        payload = self.core.get_session(session_id)
        board = chess.Board(fen)
        board.push_uci("e2e4")
        self.assertEqual(payload["puzzles"][0]["fen"], board.fen())
        self.assertEqual(payload["puzzles"][0]["moves"], "e7e5 g1f3")
        with closing(sqlite3.connect(self.puzzle_db_path)) as connection:
            stored = connection.execute(
                "SELECT fen, moves FROM puzzles WHERE puzzle_id = ?", (puzzle_id,)
            ).fetchone()
        self.assertEqual(stored, (fen, moves))

        invalid_cases = (
            ("not a fen", moves),
            (fen, "not-a-move e7e5"),
            (fen, "e2e5 e7e5"),
            (fen, "e2e4"),
        )
        for invalid_fen, invalid_moves in invalid_cases:
            with self.subTest(fen=invalid_fen, moves=invalid_moves):
                with closing(sqlite3.connect(self.puzzle_db_path)) as connection:
                    connection.execute(
                        "UPDATE puzzles SET fen = ?, moves = ? WHERE puzzle_id = ?",
                        (invalid_fen, invalid_moves, puzzle_id),
                    )
                    connection.commit()
                with self.assertRaisesRegex(RuntimeError, puzzle_id):
                    self.core.get_session(session_id)

    def test_same_day_sessions_are_isolated_and_start_resumes_latest(self):
        self._add_puzzles([f"puzzle-{number:02d}" for number in range(20)])
        self._add_weakness()
        first = self.core.create_session()
        second = self.core.create_session()

        self.assertNotEqual(first["session_id"], second["session_id"])
        self.assertEqual(first["date"], second["date"])
        self.core.record_result(first["session_id"], 1, False, 321)
        self.assertIsNone(self.core.get_session(second["session_id"])["puzzles"][0]["result"])
        self.assertEqual(self.core.start_session()["session_id"], second["session_id"])
        self.assertEqual(len(self.core.list_sessions()), 2)

    def test_history_summaries_are_per_session_and_ordered(self):
        self._add_puzzles(["history-a", "history-b", "history-c"])
        first = self._add_session("2026-10-04", ["history-a"])
        older = self._add_session("2026-10-03", ["history-b"])
        newer = self._add_session("2026-10-04", ["history-c"])
        self.core.record_result(first, 1, False, 100)
        self.core.record_result(newer, 1, True, 200)

        self.assertEqual(
            self.core.list_sessions(),
            [
                {
                    "session_id": newer,
                    "date": "2026-10-04",
                    "completed": 1,
                    "successes": 1,
                    "failures": 0,
                    "total": 1,
                },
                {
                    "session_id": first,
                    "date": "2026-10-04",
                    "completed": 1,
                    "successes": 0,
                    "failures": 1,
                    "total": 1,
                },
                {
                    "session_id": older,
                    "date": "2026-10-03",
                    "completed": 0,
                    "successes": 0,
                    "failures": 0,
                    "total": 1,
                },
            ],
        )

    def test_legacy_session_migration_preserves_data(self):
        puzzle_ids = ["legacy-one", "legacy-two"]
        self._add_puzzles(puzzle_ids)
        legacy_db = Path(self.tempdir.name) / "legacy.db"
        with closing(sqlite3.connect(legacy_db)) as connection:
            connection.executescript(
                """
                CREATE TABLE sessions (
                    session_date TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE session_puzzles (
                    session_date TEXT NOT NULL REFERENCES sessions(session_date) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    puzzle_id TEXT NOT NULL,
                    result TEXT CHECK(result IN ('success', 'failed') OR result IS NULL),
                    elapsed_ms INTEGER,
                    PRIMARY KEY(session_date, position)
                );
                CREATE TABLE puzzle_progress (
                    puzzle_id TEXT PRIMARY KEY,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    due_date TEXT NOT NULL,
                    last_result TEXT CHECK(last_result IN ('success', 'failed') OR last_result IS NULL),
                    last_elapsed_ms INTEGER
                );
                """
            )
            connection.execute("INSERT INTO sessions VALUES ('2026-10-03', '2026-10-03')")
            connection.executemany(
                "INSERT INTO session_puzzles VALUES (?, ?, ?, ?, ?)",
                [("2026-10-03", 1, puzzle_ids[0], "failed", 321), ("2026-10-03", 2, puzzle_ids[1], None, None)],
            )
            connection.execute(
                "INSERT INTO puzzle_progress VALUES (?, ?, ?, ?, ?)",
                (puzzle_ids[0], 0, "2026-10-04", "failed", 321),
            )
            connection.commit()

        migrated = Core(self.config_path, legacy_db, self.puzzle_db_path)
        with migrated._connect() as connection:
            session = connection.execute("SELECT session_id, session_date FROM sessions").fetchone()
            puzzles = connection.execute(
                "SELECT position, puzzle_id, result, elapsed_ms FROM session_puzzles "
                "WHERE session_id = ? ORDER BY position",
                (session["session_id"],),
            ).fetchall()
            progress = connection.execute(
                "SELECT success_count, due_date, last_result, last_elapsed_ms "
                "FROM puzzle_progress WHERE puzzle_id = ?",
                (puzzle_ids[0],),
            ).fetchone()

        self.assertGreater(session["session_id"], 0)
        self.assertEqual(session["session_date"], "2026-10-03")
        self.assertEqual(
            [(row["position"], row["puzzle_id"], row["result"], row["elapsed_ms"]) for row in puzzles],
            [(1, puzzle_ids[0], "failed", 321), (2, puzzle_ids[1], None, None)],
        )
        self.assertEqual(tuple(progress), (0, "2026-10-04", "failed", 321))


if __name__ == "__main__":
    main()
