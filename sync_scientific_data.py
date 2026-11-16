"""ASTRA-FIRE V2: five structured CSVs -> existing SQLite database.

Run from project root:
  python -m database.sync_scientific_data
  python -m database.sync_scientific_data --apply

Dry run is the default. All writes are transactional and idempotent.
"""
import argparse
import csv
import re
import sqlite3
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from database.models import DB_PATH

SPECS = {
    "documents": ("documents_export.csv", {"document_id", "title", "source_url", "review_status"}, "document_id"),
    "experiments": ("experiments_export.csv", {"experiment_id", "document_id", "experiment_name", "review_status"}, "experiment_id"),
    "measurements": ("measurements_export.csv", {"measurement_id", "experiment_id", "document_id", "variable", "value", "review_status"}, "measurement_id"),
    "findings": ("findings_export.csv", {"finding_id", "experiment_id", "document_id", "finding", "review_status"}, "finding_id"),
    "review": ("review_export.csv", {"document_id", "relevance", "status", "next_action"}, "document_id"),
}


def read_csvs(folder):
    out = {}
    for kind, (name, required, key) in SPECS.items():
        path = folder / name
        if not path.is_file():
            raise ValueError(f"Missing file: {path}")
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            if not required.issubset(set(reader.fieldnames or [])):
                raise ValueError(f"{name}: missing columns {sorted(required - set(reader.fieldnames or []))}")
            rows = [{k: (v or "").strip() for k, v in row.items() if k} for row in reader]
        rows = [r for r in rows if any(r.values())]
        ids = [r[key] for r in rows]
        if not all(ids) or len(ids) != len(set(ids)):
            raise ValueError(f"{name}: empty or duplicate {key}")
        out[kind] = rows
    docs = {r['document_id'] for r in out['documents']}
    exps = {r['experiment_id']: r['document_id'] for r in out['experiments']}
    for r in out['experiments']:
        if r['document_id'] not in docs:
            raise ValueError(f"Experiment {r['experiment_id']} references missing document")
    for kind in ('measurements', 'findings'):
        for r in out[kind]:
            eid = r['experiment_id']
            if eid not in exps or exps[eid] != r['document_id']:
                raise ValueError(f"{kind}: {r} has missing or mismatched experiment/document")
    for r in out['review']:
        if r['document_id'] not in docs:
            raise ValueError(f"Review references missing document {r['document_id']}")
    return out


def drive_id(url):
    m = re.search(r"/file/d/([\w-]+)", url)
    return m.group(1) if m else None


def prepare(conn):
    # Sidecar tables preserve source IDs and scientific provenance without
    # modifying the four original application-facing table schemas.
    ddl = '''
    CREATE TABLE IF NOT EXISTS scientific_sync_map (
        kind TEXT NOT NULL, source_id TEXT NOT NULL, sqlite_id INTEGER NOT NULL,
        PRIMARY KEY (kind, source_id), UNIQUE (kind, sqlite_id)
    );
    CREATE TABLE IF NOT EXISTS scientific_source_metadata (
        document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
        source_id TEXT NOT NULL UNIQUE, authors TEXT, document_type TEXT,
        gravity TEXT, review_status TEXT, relevance TEXT, next_action TEXT
    );
    CREATE TABLE IF NOT EXISTS scientific_experiment_metadata (
        experiment_id INTEGER PRIMARY KEY REFERENCES experiments(id) ON DELETE CASCADE,
        source_id TEXT NOT NULL UNIQUE, geometry TEXT, conditions TEXT,
        source_page_pdf TEXT, review_status TEXT
    );
    CREATE TABLE IF NOT EXISTS scientific_measurement_metadata (
        measurement_id INTEGER PRIMARY KEY REFERENCES measurements(id) ON DELETE CASCADE,
        source_id TEXT NOT NULL UNIQUE, document_id INTEGER REFERENCES documents(id),
        evidence_type TEXT, condition_text TEXT, source_page_pdf TEXT,
        review_status TEXT
    );
    CREATE TABLE IF NOT EXISTS scientific_finding_metadata (
        finding_id INTEGER PRIMARY KEY REFERENCES findings(id) ON DELETE CASCADE,
        source_id TEXT NOT NULL UNIQUE, evidence_type TEXT,
        source_page_pdf TEXT, limitations TEXT, review_status TEXT
    );
    '''
    for statement in ddl.split(';'):
        if statement.strip():
            conn.execute(statement)


def mapped(conn, kind, source_id):
    row = conn.execute('SELECT sqlite_id FROM scientific_sync_map WHERE kind=? AND source_id=?', (kind, source_id)).fetchone()
    return row[0] if row else None


def put_map(conn, kind, source_id, sqlite_id):
    conn.execute('INSERT INTO scientific_sync_map(kind,source_id,sqlite_id) VALUES (?,?,?)', (kind, source_id, sqlite_id))


def sync(conn, data):
    stats = Counter()
    doc_map, exp_map = {}, {}
    cols = {r[1] for r in conn.execute('PRAGMA table_info(documents)')}
    if 'drive_id' not in cols:
        raise ValueError('documents.drive_id missing: apply INVENTORY synchronization first')
    for r in data['documents']:
        sid = r['document_id']
        did = drive_id(r['source_url'])
        if not did:
            raise ValueError(f'{sid}: unsupported or missing Google Drive file URL')
        matches = conn.execute('SELECT id FROM documents WHERE drive_id=?', (did,)).fetchall()
        if len(matches) != 1:
            raise ValueError(f'{sid}: expected exactly one inventory document for Drive ID {did}, found {len(matches)}')
        pk = matches[0][0]
        old = mapped(conn, 'documents', sid)
        if old is not None and old != pk:
            raise ValueError(f'{sid}: source mapping conflicts with inventory')
        if old is None:
            put_map(conn, 'documents', sid, pk)
        doc_map[sid] = pk
        year = r.get('year', '')
        if year and (not year.isdigit() or not 1000 <= int(year) <= 3000):
            raise ValueError(f'{sid}: invalid year {year!r}')
        conn.execute('''UPDATE documents SET category=?, publication_year=COALESCE(?,publication_year)
                        WHERE id=?''', (r.get('category_proposed') or None, int(year) if year else None, pk))
        conn.execute('''INSERT INTO scientific_source_metadata
            (document_id,source_id,authors,document_type,gravity,review_status)
            VALUES (?,?,?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET
            authors=excluded.authors,document_type=excluded.document_type,
            gravity=excluded.gravity,review_status=excluded.review_status''',
            (pk,sid,r.get('authors'),r.get('document_type'),r.get('gravity'),r['review_status']))
        stats['documents_matched'] += 1
    for r in data['experiments']:
        sid = r['experiment_id']; pk = mapped(conn,'experiments',sid)
        did = doc_map[r['document_id']]
        values = (did,r['experiment_name'],r.get('category'),None,r.get('gravity'),r.get('material_or_fuel'),
                  f"Geometry: {r.get('geometry','')}\nConditions: {r.get('conditions','')}")
        if pk is None:
            cur = conn.execute('''INSERT INTO experiments
              (document_id,experiment_name,experiment_type,environment,gravity_condition,fuel_type,description)
              VALUES (?,?,?,?,?,?,?)''',values)
            pk=cur.lastrowid; put_map(conn,'experiments',sid,pk);stats['experiments_new']+=1
        else:
            if conn.execute('SELECT 1 FROM experiments WHERE id=?',(pk,)).fetchone() is None:
                raise ValueError(f'Mapped experiment {sid} was deleted')
            conn.execute('''UPDATE experiments SET document_id=?,experiment_name=?,experiment_type=?,
              environment=?,gravity_condition=?,fuel_type=?,description=? WHERE id=?''',(*values,pk))
            stats['experiments_updated']+=1
        exp_map[sid]=pk
        conn.execute('''INSERT INTO scientific_experiment_metadata
          (experiment_id,source_id,geometry,conditions,source_page_pdf,review_status)
          VALUES (?,?,?,?,?,?) ON CONFLICT(experiment_id) DO UPDATE SET
          geometry=excluded.geometry,conditions=excluded.conditions,
          source_page_pdf=excluded.source_page_pdf,review_status=excluded.review_status''',
          (pk,sid,r.get('geometry'),r.get('conditions'),r.get('source_page_pdf'),r['review_status']))
    for r in data['measurements']:
        sid=r['measurement_id'];pk=mapped(conn,'measurements',sid)
        value=r['value']; numeric=None
        if value:
            try: numeric=float(value)
            except ValueError: raise ValueError(f'{sid}: nonnumeric measurement value {value!r}')
        values=(exp_map[r['experiment_id']],r['variable'],numeric,r.get('unit'),r.get('evidence_type'),r.get('condition'))
        if pk is None:
            cur=conn.execute('''INSERT INTO measurements
                (experiment_id,variable_name,value,unit,measurement_method,notes) VALUES (?,?,?,?,?,?)''',values)
            pk=cur.lastrowid;put_map(conn,'measurements',sid,pk);stats['measurements_new']+=1
        else:
            if conn.execute('SELECT 1 FROM measurements WHERE id=?',(pk,)).fetchone() is None:
                raise ValueError(f'Mapped measurement {sid} was deleted')
            conn.execute('''UPDATE measurements SET experiment_id=?,variable_name=?,value=?,unit=?,
                measurement_method=?,notes=? WHERE id=?''',(*values,pk));stats['measurements_updated']+=1
        conn.execute('''INSERT INTO scientific_measurement_metadata
            (measurement_id,source_id,document_id,evidence_type,condition_text,source_page_pdf,review_status)
            VALUES (?,?,?,?,?,?,?) ON CONFLICT(measurement_id) DO UPDATE SET
            document_id=excluded.document_id,evidence_type=excluded.evidence_type,
            condition_text=excluded.condition_text,source_page_pdf=excluded.source_page_pdf,
            review_status=excluded.review_status''',
            (pk,sid,doc_map[r['document_id']],r.get('evidence_type'),r.get('condition'),r.get('source_page_pdf'),r['review_status']))
    for r in data['findings']:
        sid=r['finding_id'];pk=mapped(conn,'findings',sid)
        values=(doc_map[r['document_id']],exp_map[r['experiment_id']],r['finding'],r.get('evidence_type'))
        if pk is None:
            cur=conn.execute('''INSERT INTO findings
              (document_id,experiment_id,finding_text,evidence_level) VALUES (?,?,?,?)''',values)
            pk=cur.lastrowid;put_map(conn,'findings',sid,pk);stats['findings_new']+=1
        else:
            if conn.execute('SELECT 1 FROM findings WHERE id=?',(pk,)).fetchone() is None:
                raise ValueError(f'Mapped finding {sid} was deleted')
            conn.execute('''UPDATE findings SET document_id=?,experiment_id=?,finding_text=?,evidence_level=?
              WHERE id=?''',(*values,pk));stats['findings_updated']+=1
        conn.execute('''INSERT INTO scientific_finding_metadata
          (finding_id,source_id,evidence_type,source_page_pdf,limitations,review_status)
          VALUES (?,?,?,?,?,?) ON CONFLICT(finding_id) DO UPDATE SET
          evidence_type=excluded.evidence_type,source_page_pdf=excluded.source_page_pdf,
          limitations=excluded.limitations,review_status=excluded.review_status''',
          (pk,sid,r.get('evidence_type'),r.get('source_page_pdf'),r.get('limitations'),r['review_status']))
    for r in data['review']:
        conn.execute('''UPDATE scientific_source_metadata SET relevance=?,next_action=?
          WHERE document_id=?''',(r['relevance'],r['next_action'],doc_map[r['document_id']]))
        stats['reviews_updated']+=1
    return stats


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--folder',type=Path,default=Path('data'))
    p.add_argument('--apply',action='store_true')
    args=p.parse_args()
    data=read_csvs(args.folder)
    if not DB_PATH.is_file():
        p.error(f'SQLite database not found: {DB_PATH}')
    conn=sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        conn.execute('BEGIN')
        prepare(conn)
        stats=sync(conn,data)
        invalid=conn.execute('PRAGMA foreign_key_check').fetchall()
        if invalid:
            raise ValueError(f'Foreign key violations: {invalid[:5]}')
        if args.apply:conn.commit()
        else:conn.rollback()
        print('Mode:', 'APPLY' if args.apply else 'DRY RUN')
        for k in ('documents_matched','experiments_new','experiments_updated',
                  'measurements_new','measurements_updated','findings_new','findings_updated','reviews_updated'):
            print(f'{k}: {stats[k]}')
        print('Committed successfully' if args.apply else 'No changes saved; review counts before --apply')
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__=='__main__':main()
