"""ASTRA-FIRE AI V2: safe, repeatable INVENTORY CSV -> SQLite synchronization.
Run from project root: python -m database.sync_scientific_inventory --csv data/inventory_export.csv
Add --apply after reviewing the dry run. No third-party dependencies.
"""
import argparse
import csv
import sqlite3
from collections import Counter
from pathlib import Path

from database.models import DB_PATH, initialize_database

REQUIRED = {"drive_id", "filename", "type", "size_bytes", "source_url", "review_status", "relevance_note"}


def clean(value):
    return (value or "").strip()


def read_inventory(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        if not REQUIRED.issubset(headers):
            raise ValueError(f"Missing CSV columns: {sorted(REQUIRED - headers)}")
        rows = [{key: clean(value) for key, value in row.items() if key} for row in reader]
    rows = [row for row in rows if any(row.values())]
    ids = [r["drive_id"] for r in rows]
    if any(not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("Empty or duplicated drive_id in CSV; no changes made")
    return rows


def ensure_columns(conn):
    existing = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    for name, dtype in (
        ("drive_id", "TEXT"), ("source_url", "TEXT"),
        ("review_status", "TEXT"), ("relevance_note", "TEXT"),
        ("size_bytes", "INTEGER"),
    ):
        if name not in existing:
            conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {dtype}")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_drive_id ON documents(drive_id)")


def sync(conn, rows, apply):
    stats = Counter()
    conn.execute("SAVEPOINT inventory_sync")
    try:
        ensure_columns(conn)
        for row in rows:
            drive_id, filename = row["drive_id"], row["filename"]
            existing = conn.execute("SELECT id FROM documents WHERE drive_id = ?", (drive_id,)).fetchone()
            if not existing:
                matches = conn.execute("SELECT id FROM documents WHERE filename = ?", (filename,)).fetchall()
                if len(matches) > 1:
                    raise ValueError(f"Ambiguous filename {filename!r}: {len(matches)} matches; stopped")
                existing = matches[0] if matches else None
                if existing:
                    old = conn.execute("SELECT drive_id FROM documents WHERE id = ?", (existing[0],)).fetchone()[0]
                    if old and old != drive_id:
                        raise ValueError(f"Filename {filename!r} is associated with another Drive ID; stopped")
            size = int(row["size_bytes"]) if row["size_bytes"].isdigit() else None
            data = (drive_id, row["source_url"], row["review_status"], row["relevance_note"], size)
            if existing:
                conn.execute("""UPDATE documents SET drive_id=?, source_url=?, review_status=?,
                    relevance_note=?, size_bytes=? WHERE id=?""", (*data, existing[0]))
                stats["matched_and_updated"] += 1
            else:
                conn.execute("""INSERT INTO documents
                    (title, filename, file_type, source, drive_id, source_url,
                     review_status, relevance_note, size_bytes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (Path(filename).stem, filename, row["type"], "Google Drive",
                     drive_id, row["source_url"], row["review_status"],
                     row["relevance_note"], size))
                stats["inserted"] += 1
        if apply:
            conn.execute("RELEASE SAVEPOINT inventory_sync")
        else:
            conn.execute("ROLLBACK TO SAVEPOINT inventory_sync")
            conn.execute("RELEASE SAVEPOINT inventory_sync")
        return stats
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT inventory_sync")
        conn.execute("RELEASE SAVEPOINT inventory_sync")
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=Path("data/inventory_export.csv"))
    parser.add_argument("--apply", action="store_true", help="Commit changes (default is dry run)")
    args = parser.parse_args()
    if not args.csv.is_file():
        parser.error(f"CSV not found: {args.csv}")
    rows = read_inventory(args.csv)
    if args.apply:
        initialize_database()
    elif not DB_PATH.is_file():
        parser.error(f"Database not found: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        before = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        result = sync(conn, rows, args.apply)
        if args.apply:
            conn.commit()
        print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
        print(f"CSV records: {len(rows)} | Existing documents: {before}")
        print(f"Matched/updated: {result['matched_and_updated']} | New: {result['inserted']}")
        print("Committed successfully" if args.apply else "No changes saved; review counts before --apply")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
