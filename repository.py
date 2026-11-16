
from database.models import get_connection, initialize_database


def add_document(
    title,
    filename=None,
    file_type=None,
    category=None,
    source=None,
    publication_year=None,
    abstract=None,
    file_path=None
):
    """Guarda un documento en la biblioteca científica oficial."""
    initialize_database()

    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO documents (
                title, filename, file_type, category,
                source, publication_year, abstract, file_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            title, filename, file_type, category,
            source, publication_year, abstract, file_path
        ))
        return cursor.lastrowid


def get_documents():
    """Recupera todos los documentos registrados."""
    initialize_database()

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM documents
            ORDER BY uploaded_at DESC, id DESC
        """).fetchall()

        return [dict(row) for row in rows]


def search_documents(query):
    """Busca investigaciones por título, categoría o resumen."""
    initialize_database()
    search = f"%{query}%"

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM documents
            WHERE title LIKE ?
               OR category LIKE ?
               OR abstract LIKE ?
               OR source LIKE ?
            ORDER BY id DESC
        """, (search, search, search, search)).fetchall()

        return [dict(row) for row in rows]



def add_experiment(
    document_id,
    experiment_name,
    experiment_type=None,
    objective=None,
    methodology=None,
    environment=None,
    gravity_condition=None,
    fuel_type=None,
    description=None
):
    """Registra un experimento usando las columnas reales de SQLite."""
    initialize_database()

    details = []
    if description:
        details.append(description)
    if objective:
        details.append(f"Objective: {objective}")
    if methodology:
        details.append(f"Methodology: {methodology}")

    full_description = "\n".join(details) or None

    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO experiments (
                document_id,
                experiment_name,
                experiment_type,
                environment,
                gravity_condition,
                fuel_type,
                description
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            document_id,
            experiment_name,
            experiment_type,
            environment,
            gravity_condition,
            fuel_type,
            full_description
        ))

        return cursor.lastrowid



def add_measurement(
    experiment_id,
    variable_name,
    value=None,
    unit=None,
    measurement_method=None
):
    """Registra una medición experimental."""
    initialize_database()

    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO measurements (
                experiment_id, variable_name, value,
                unit, measurement_method
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            experiment_id, variable_name, value,
            unit, measurement_method
        ))
        return cursor.lastrowid



def add_finding(
    document_id,
    description,
    experiment_id=None,
    finding_type=None,
    confidence_level=None
):
    """Guarda un hallazgo científico asociado a un documento."""
    initialize_database()

    finding_text = description

    if finding_type:
        finding_text = (
            f"Finding type: {finding_type}\n"
            f"{description}"
        )

    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO findings (
                document_id,
                experiment_id,
                finding_text,
                evidence_level
            )
            VALUES (?, ?, ?, ?)
        """, (
            document_id,
            experiment_id,
            finding_text,
            confidence_level
        ))

        return cursor.lastrowid



def get_document_evidence(document_id):
    """Recupera un documento y su evidencia relacionada."""
    initialize_database()

    with get_connection() as conn:
        document = conn.execute(
            "SELECT * FROM documents WHERE id = ?",
            (document_id,)
        ).fetchone()

        if document is None:
            return None

        experiments = conn.execute("""
            SELECT * FROM experiments
            WHERE document_id = ?
        """, (document_id,)).fetchall()

        measurements = conn.execute("""
            SELECT m.*
            FROM measurements m
            JOIN experiments e ON m.experiment_id = e.id
            WHERE e.document_id = ?
        """, (document_id,)).fetchall()

        findings = conn.execute("""
            SELECT * FROM findings
            WHERE document_id = ?
        """, (document_id,)).fetchall()

        return {
            "document": dict(document),
            "experiments": [dict(x) for x in experiments],
            "measurements": [dict(x) for x in measurements],
            "findings": [dict(x) for x in findings]
        }
