import argparse
import csv
import sqlite3
from pathlib import Path

import chess
import compression.zstd as zstd


SUPPORTED_THEMES = {"mate", "fork", "hangingPiece", "pin", "discoveredAttack"}
EXCLUDED_THEMES = {"promotion", "underPromotion", "mateIn1"}
BATCH_SIZE = 1_000


def import_puzzles(source: Path, database: Path) -> int:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS puzzles (
                puzzle_id TEXT PRIMARY KEY,
                fen TEXT NOT NULL,
                moves TEXT NOT NULL,
                rating INTEGER NOT NULL,
                themes TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_puzzles_rating ON puzzles(rating);
            """
        )

        with zstd.open(source, "rt", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"PuzzleId", "FEN", "Moves", "Rating", "Themes"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                missing = ", ".join(sorted(required - set(reader.fieldnames or [])))
                raise ValueError(f"missing required CSV columns: {missing}")

            imported = 0
            with connection:
                connection.execute("DELETE FROM puzzles")
                batch = []
                for row in reader:
                    puzzle_id = row.get("PuzzleId")
                    fen = row.get("FEN")
                    moves = row.get("Moves") or ""
                    themes = set((row.get("Themes") or "").split())
                    if not themes & SUPPORTED_THEMES or themes & EXCLUDED_THEMES:
                        continue
                    if not puzzle_id or not fen or not moves:
                        continue
                    if any(
                        len(move) == 5 and move[-1] in "qrbn"
                        for move in moves.split()
                    ):
                        continue
                    try:
                        rating = int(row.get("Rating"))
                    except (TypeError, ValueError):
                        continue
                    try:
                        board = chess.Board(fen)
                        for move_uci in moves.split():
                            move = chess.Move.from_uci(move_uci)
                            if not board.is_legal(move):
                                raise ValueError(f"illegal move: {move_uci}")
                            board.push(move)
                    except (ValueError, chess.InvalidMoveError):
                        continue

                    batch.append(
                        (
                            puzzle_id,
                            fen,
                            moves,
                            rating,
                            " ".join(sorted(themes & SUPPORTED_THEMES)),
                        )
                    )
                    if len(batch) == BATCH_SIZE:
                        connection.executemany(
                            "INSERT OR REPLACE INTO puzzles "
                            "(puzzle_id, fen, moves, rating, themes) VALUES (?, ?, ?, ?, ?)",
                            batch,
                        )
                        imported += len(batch)
                        batch.clear()

                if batch:
                    connection.executemany(
                        "INSERT OR REPLACE INTO puzzles "
                        "(puzzle_id, fen, moves, rating, themes) VALUES (?, ?, ?, ?, ?)",
                        batch,
                    )
                    imported += len(batch)
        return imported
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import supported Lichess puzzles.")
    parser.add_argument("source", type=Path, help="Lichess puzzles.csv.zst")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "puzzles.db",
    )
    args = parser.parse_args()
    print(f"Imported {import_puzzles(args.source, args.database)} puzzles")


if __name__ == "__main__":
    main()
