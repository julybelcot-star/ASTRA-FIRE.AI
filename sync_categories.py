"""Safe category sync for ASTRA-FIRE. Dry-run by default; --apply commits.
Usage: python -m database.sync_categories --csv data/categories_review.csv [--apply]
"""
import argparse
import csv
import shutil
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from database.models import DB_PATH

CATEGORIES = (
    'Spacecraft Fire Safety', 'Droplets',
    'Gaseous - Premixed and Non-Premixed',
    'High Pressure / Supercritical', 'Solid Fuels',
)

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--csv', type=Path, default=Path('data/categories_review.csv'))
    p.add_argument('--apply', action='store_true')
    a = p.parse_args()
    if not a.csv.is_file() or not DB_PATH.is_file():
        p.error('CSV or SQLite database not found. No changes made.')
    with a.csv.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not {'drive_id', 'filename', 'category'}.issubset(reader.fieldnames or []):
            p.error('CSV must include drive_id, filename, category')
        rows = list(reader)
    planned = []
    seen = set()
    conn = sqlite3.connect(DB_PATH)
    try:
        cols = {r[1] for r in conn.execute('PRAGMA table_info(documents)')}
        if not {'drive_id','filename','category'}.issubset(cols):
            p.error('Missing required documents columns; no changes made.')
        for r in rows:
            cat = (r.get('category') or '').strip()
            if not cat:
                continue
            if cat not in CATEGORIES:
                p.error(f'Invalid category {cat!r} for {r.get("filename")!r}')
            drive_id = (r.get('drive_id') or '').strip()
            filename = (r.get('filename') or '').strip()
            if not drive_id or drive_id in seen:
                p.error(f'Missing or duplicate drive_id: {drive_id!r}')
            seen.add(drive_id)
            matches = conn.execute('SELECT id, filename, category FROM documents WHERE drive_id=?', (drive_id,)).fetchall()
            if len(matches) != 1:
                p.error(f'Drive ID not uniquely matched in SQLite: {drive_id}')
            doc_id, db_filename, old_category = matches[0]
            if db_filename != filename:
                p.error(f'Filename mismatch for {drive_id}: {filename!r} vs {db_filename!r}')
            if old_category and old_category.strip() and old_category.strip() != cat:
                p.error(f'Conflicting existing category for {filename!r}: {old_category!r} vs {cat!r}; resolve manually')
            if (old_category or '').strip() != cat:
                planned.append((cat, doc_id))
        print(f'Mode: {"APPLY" if a.apply else "DRY RUN"} | rows: {len(rows)} | proposed updates: {len(planned)}')
        print('Proposed category counts:', dict(Counter(cat for cat, _ in planned)))
        if a.apply:
            if planned:
                backup = DB_PATH.parent / 'backups' / f'astra_fire_before_categories_{datetime.now():%Y%m%d_%H%M%S}.db'
                backup.parent.mkdir(parents=True, exist_ok=True)
                destination = sqlite3.connect(backup)
                try:
                    conn.backup(destination)
                finally:
                    destination.close()
                print('Backup:', backup)
                conn.executemany('UPDATE documents SET category=? WHERE id=?', planned)
                conn.commit()
            print('Committed successfully')
        else:
            print('No changes saved. Review categories_review.csv and run --apply when ready.')
    finally:
        conn.close()

if __name__ == '__main__':
    main()
