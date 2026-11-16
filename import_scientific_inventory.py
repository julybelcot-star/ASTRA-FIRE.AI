"""Importa metadatos del inventario ASTRA-FIRE a SQLite sin alterar documentos originales.
Uso: python import_scientific_inventory.py ruta/al/INVENTORY.csv
"""
import csv
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'data' / 'astra_fire.db'
REQUIRED = {'drive_id', 'filename', 'type', 'size_bytes', 'source_url', 'review_status', 'relevance_note'}


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Uso: python import_scientific_inventory.py "ruta/al/INVENTORY.csv"')
    inventory = Path(sys.argv[1]).expanduser().resolve()
    if not inventory.is_file():
        raise SystemExit(f'No se encontró el CSV: {inventory}')
    if not DB.is_file():
        raise SystemExit(f'No se encontró SQLite en {DB}. Coloca este script en la raíz ASTRA-FIRE-V2.')
    with inventory.open('r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f'Faltan columnas: {sorted(missing)}')
        rows = list(reader)
    ids = [(r['drive_id'] or '').strip() for r in rows]
    if not all(ids) or len(ids) != len(set(ids)):
        raise SystemExit('Hay drive_id vacíos o repetidos en el CSV; no se importó nada.')
    if any(not (r['filename'] or '').strip() for r in rows):
        raise SystemExit('Hay filenames vacíos; no se importó nada.')

    backup = DB.with_name(f'astra_fire_backup_{datetime.now():%Y%m%d_%H%M%S}.db')
    with sqlite3.connect(DB) as original, sqlite3.connect(backup) as target:
        original.backup(target)
    print(f'Respaldo: {backup}')

    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        cols = {r['name'] for r in conn.execute('PRAGMA table_info(documents)')}
        if not {'id', 'title', 'filename', 'file_type', 'source', 'file_path'} <= cols:
            raise SystemExit('La tabla documents no coincide con la estructura esperada; no se importó nada.')
        conn.execute('BEGIN IMMEDIATE')
        for col, typ in [('drive_id', 'TEXT'), ('source_url', 'TEXT'), ('review_status', 'TEXT'),
                         ('relevance_note', 'TEXT'), ('size_bytes', 'INTEGER')]:
            if col not in cols:
                conn.execute(f'ALTER TABLE documents ADD COLUMN {col} {typ}')
        duplicates = conn.execute('SELECT drive_id FROM documents WHERE drive_id IS NOT NULL GROUP BY drive_id HAVING COUNT(*) > 1').fetchall()
        if duplicates:
            raise SystemExit('SQLite ya tiene drive_id duplicados; se canceló la importación.')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_drive_id ON documents(drive_id)')
        counts = Counter()
        for r in rows:
            did = r['drive_id'].strip()
            filename = r['filename'].strip()
            existing = conn.execute('SELECT id FROM documents WHERE drive_id = ?', (did,)).fetchone()
            size = int(r['size_bytes']) if (r['size_bytes'] or '').strip().isdigit() else None
            vals = (filename, filename, (r['type'] or '').strip(),
                    'Google Drive scientific inventory', (r['source_url'] or '').strip(),
                    did, (r['source_url'] or '').strip(), (r['review_status'] or '').strip(),
                    (r['relevance_note'] or '').strip(), size)
            if existing:
                conn.execute('''UPDATE documents SET drive_id=?, source_url=?, review_status=?,
                    relevance_note=?, size_bytes=? WHERE id=?''',
                    (did, vals[6], vals[7], vals[8], vals[9], existing['id']))
                counts['actualizados'] += 1
            else:
                conn.execute('''INSERT INTO documents
                    (title, filename, file_type, source, file_path, drive_id, source_url,
                     review_status, relevance_note, size_bytes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', vals)
                counts['insertados'] += 1
        print(f"Insertados: {counts['insertados']} | Actualizados: {counts['actualizados']}")
        print('Total documentos SQLite:', conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0])
        print('Documentos con drive_id:', conn.execute('SELECT COUNT(*) FROM documents WHERE drive_id IS NOT NULL').fetchone()[0])
        print('No se han importado contenidos ni mediciones científicas.')


if __name__ == '__main__':
    main()
