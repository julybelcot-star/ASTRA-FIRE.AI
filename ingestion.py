
from pathlib import Path
import hashlib
import shutil
import sqlite3

from database.models import (
    get_connection,
    initialize_database,
)
from database.repository import add_document


BASE_DIR = Path(__file__).resolve().parent.parent
LIBRARY_DIR = BASE_DIR / "data" / "scientific_library"

SUPPORTED_TYPES = {".pdf", ".xlsx", ".xls", ".csv"}


def prepare_ingestion():
    """Prepara la biblioteca y el control de duplicados."""
    initialize_database()
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS document_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                sha256 TEXT NOT NULL UNIQUE,
                original_filename TEXT NOT NULL,
                FOREIGN KEY (document_id)
                    REFERENCES documents(id)
                    ON DELETE CASCADE
            )
        """)


def calculate_hash(file_path):
    """Calcula la huella digital del archivo."""
    sha = hashlib.sha256()

    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha.update(chunk)

    return sha.hexdigest()


def ingest_document(file_path, source=None):
    """Importa un documento a la biblioteca oficial."""
    prepare_ingestion()

    file_path = Path(file_path)

    if not file_path.is_file():
        raise FileNotFoundError(file_path)

    suffix = file_path.suffix.lower()

    if suffix not in SUPPORTED_TYPES:
        raise ValueError(
            f"Unsupported file type: {suffix}"
        )

    fingerprint = calculate_hash(file_path)

    with get_connection() as conn:
        existing = conn.execute("""
            SELECT document_id
            FROM document_files
            WHERE sha256 = ?
        """, (fingerprint,)).fetchone()

    if existing:
        return {
            "status": "duplicate",
            "document_id": existing["document_id"],
            "filename": file_path.name,
        }

    destination = LIBRARY_DIR / (
        fingerprint[:16] + suffix
    )

    if not destination.exists():
        shutil.copy2(file_path, destination)

    try:
        with get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO documents (
                    title, filename, file_type,
                    source, file_path
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                file_path.stem,
                file_path.name,
                suffix.lstrip("."),
                source,
                str(destination),
            ))

            document_id = cursor.lastrowid

            conn.execute("""
                INSERT INTO document_files (
                    document_id, sha256, original_filename
                )
                VALUES (?, ?, ?)
            """, (
                document_id,
                fingerprint,
                file_path.name,
            ))

        return {
            "status": "imported",
            "document_id": document_id,
            "filename": file_path.name,
        }

    except sqlite3.IntegrityError:
        with get_connection() as conn:
            existing = conn.execute("""
                SELECT document_id
                FROM document_files
                WHERE sha256 = ?
            """, (fingerprint,)).fetchone()

        if existing:
            return {
                "status": "duplicate",
                "document_id": existing["document_id"],
                "filename": file_path.name,
            }

        raise


def ingest_folder(folder_path):
    """Importa los documentos de una carpeta local."""
    folder = Path(folder_path)

    if not folder.is_dir():
        raise NotADirectoryError(folder)

    results = []

    for file_path in sorted(folder.rglob("*")):
        if not file_path.is_file():
            continue

        if file_path.suffix.lower() not in SUPPORTED_TYPES:
            continue

        try:
            result = ingest_document(file_path)
        except Exception as error:
            result = {
                "status": "error",
                "filename": file_path.name,
                "message": str(error),
            }

        results.append(result)

    return results


if __name__ == "__main__":
    prepare_ingestion()
    print("ASTRA-FIRE ingestion module ready")
