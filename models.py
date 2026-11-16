
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "astra_fire.db"


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def initialize_database():
    with get_connection() as conn:

        # 1. Biblioteca científica oficial
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                filename TEXT,
                file_type TEXT,
                category TEXT,
                source TEXT,
                publication_year INTEGER,
                abstract TEXT,
                file_path TEXT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. Experimentos científicos
        conn.execute("""
            CREATE TABLE IF NOT EXISTS experiments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                experiment_name TEXT,
                experiment_type TEXT,
                environment TEXT,
                gravity_condition TEXT,
                fuel_type TEXT,
                description TEXT,
                FOREIGN KEY (document_id)
                    REFERENCES documents(id)
                    ON DELETE CASCADE
            )
        """)

        # 3. Mediciones experimentales
        conn.execute("""
            CREATE TABLE IF NOT EXISTS measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER NOT NULL,
                variable_name TEXT NOT NULL,
                value REAL,
                unit TEXT,
                measurement_method TEXT,
                notes TEXT,
                FOREIGN KEY (experiment_id)
                    REFERENCES experiments(id)
                    ON DELETE CASCADE
            )
        """)

        # 4. Hallazgos científicos
        conn.execute("""
            CREATE TABLE IF NOT EXISTS findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                experiment_id INTEGER,
                finding_text TEXT NOT NULL,
                evidence_level TEXT,
                FOREIGN KEY (document_id)
                    REFERENCES documents(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (experiment_id)
                    REFERENCES experiments(id)
                    ON DELETE SET NULL
            )
        """)

        conn.commit()


if __name__ == "__main__":
    initialize_database()
    print("ASTRA-FIRE Scientific Database initialized successfully")
