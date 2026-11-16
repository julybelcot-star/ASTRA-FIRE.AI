"""Import the INVENTORY tab's downloaded CSV into ASTRA-FIRE SQLite.
Dry run: python -m database.sync_sheet_categories --csv data/inventory_sheet.csv
Apply:   python -m database.sync_sheet_categories --csv data/inventory_sheet.csv --apply
"""
import argparse
import csv
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from database.models import DB_PATH, initialize_database

CATEGORIES = {'Spacecraft Fire Safety', 'Droplets', 'Gaseous - Premixed and Non-Premixed', 'High Pressure / Supercritical', 'Solid Fuels'}
PENDING = {'', 'Unclassified / Needs Review'}
REQUIRED = {'drive_id', 'filename', 'type', 'category', 'classification_status', 'review_status', 'relevance_note', 'source_url', 'size_bytes'}

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--csv', type=Path, default=Path('data/inventory_sheet.csv'))
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    if not args.csv.is_file():
        p.error(f'CSV not found: {args.csv}')
    with args.csv.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            p.error(f'Missing columns: {sorted(missing)}')
        rows = list(reader)
    if len(rows) != 190:
        p.error(f'Expected 190 inventory records, found {len(rows)}; nothing changed')
    ids = [(r['drive_id'] or '').strip() for r in rows]
    if any(not x for x in ids) or len(set(ids)) != len(ids):
        p.error('Blank or duplicate Drive IDs; nothing changed')
    for r in rows:
        cat = (r['category'] or '').strip()
        if cat not in CATEGORIES | PENDING:
            p.error(f'Unsupported category {cat!r} for {r["filename"]!r}')
    initialize_database()
    if args.apply:
        # Back up before opening the write transaction.
        backup=DB_PATH.parent/'backups'/f'astra_fire_before_sheet_sync_{datetime.now():%Y%m%d_%H%M%S}.db'
        backup.parent.mkdir(parents=True,exist_ok=True)
        source=sqlite3.connect(DB_PATH)
        dest=sqlite3.connect(backup)
        try: source.backup(dest)
        finally:
            dest.close()
            source.close()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute('PRAGMA foreign_keys = ON')
        columns = {r[1] for r in conn.execute('PRAGMA table_info(documents)')}
        if 'category' not in columns:
            p.error('documents.category is missing; nothing changed')
        changes = Counter()
        conn.execute('SAVEPOINT import_categories')
        try:
            for col, dtype in [('drive_id','TEXT'),('source_url','TEXT'),('review_status','TEXT'),('relevance_note','TEXT'),('size_bytes','INTEGER')]:
                if col not in columns:
                    conn.execute(f'ALTER TABLE documents ADD COLUMN {col} {dtype}')
            for r in rows:
                did, filename = r['drive_id'].strip(), r['filename'].strip()
                matched = conn.execute('SELECT id, filename, drive_id, category FROM documents WHERE drive_id=?', (did,)).fetchall()
                if not matched:
                    matched = conn.execute('SELECT id, filename, drive_id, category FROM documents WHERE filename=?', (filename,)).fetchall()
                if len(matched) > 1:
                    raise ValueError(f'Ambiguous matching document: {filename}')
                if matched:
                    pk, dbfilename, dbid, oldcat = matched[0]
                    if dbfilename != filename or (dbid and dbid != did):
                        raise ValueError(f'ID/filename mismatch: {filename}')
                    # Preserve preexisting classifications when Sheet still says pending.
                    cat = r['category'].strip()
                    newcat = cat if cat in CATEGORIES else oldcat
                    conn.execute('''UPDATE documents SET category=?, drive_id=?, source_url=?, review_status=?, relevance_note=?, size_bytes=? WHERE id=?''',
                                 (newcat, did, r['source_url'], r['review_status'], r['relevance_note'], int(r['size_bytes']) if r['size_bytes'].isdigit() else None, pk))
                    changes['updated'] += 1
                else:
                    cat = r['category'].strip()
                    conn.execute('''INSERT INTO documents (title,filename,file_type,category,source,drive_id,source_url,review_status,relevance_note,size_bytes) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                                 (Path(filename).stem,filename,r['type'],cat if cat in CATEGORIES else None,'Google Drive',did,r['source_url'],r['review_status'],r['relevance_note'],int(r['size_bytes']) if r['size_bytes'].isdigit() else None))
                    changes['inserted'] += 1
            total = conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
            counts = dict(conn.execute("SELECT COALESCE(category,'Unclassified / Needs Review'), COUNT(*) FROM documents WHERE drive_id IN ("+','.join('?' for _ in ids)+") GROUP BY COALESCE(category,'Unclassified / Needs Review')",ids).fetchall())
            print(f'CSV: {len(rows)} | matched/updated: {changes["updated"]} | inserted: {changes["inserted"]} | SQLite total: {total}')
            print('Categories in imported inventory:', counts)
            if args.apply:
                conn.execute('RELEASE SAVEPOINT import_categories')
                conn.commit()
                print(f'Applied. Backup: {backup}')
            else:
                conn.execute('ROLLBACK TO SAVEPOINT import_categories')
                conn.execute('RELEASE SAVEPOINT import_categories')
                print('DRY RUN: no changes saved. Add --apply to save.')
        except Exception:
            conn.execute('ROLLBACK TO SAVEPOINT import_categories')
            conn.execute('RELEASE SAVEPOINT import_categories')
            raise
    finally:
        conn.close()

if __name__ == '__main__':
    main()
