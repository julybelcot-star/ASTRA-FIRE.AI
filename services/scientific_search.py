
import re
import unicodedata

from database.models import get_connection, initialize_database


TRANSLATIONS = {
    "combustion": ["combustion"],
    "microgravedad": ["microgravity"],
    "gravedad": ["gravity"],
    "llama": ["flame"],
    "llamas": ["flame"],
    "fuego": ["fire"],
    "oxigeno": ["oxygen"],
    "temperatura": ["temperature"],
    "propagacion": ["propagation"],
    "experimento": ["experiment"],
    "experimentos": ["experiment"],
    "investigacion": ["research"],
    "investigaciones": ["research"],
    "combustible": ["fuel"],
    "presion": ["pressure"],
    "ignicion": ["ignition"],
    "radiacion": ["radiation"],
    "humo": ["smoke"],
    "seguridad": ["safety"],
}

STOPWORDS = {
    "que", "como", "cuales", "los", "las", "del",
    "con", "para", "por", "una", "uno", "sobre",
    "entre", "estudian", "estudia", "documentos",
    "the", "and", "are", "what", "which",
    "about", "does", "from", "show", "find"
}


def normalize_text(text):
    text = text.lower()
    return "".join(
        char for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )


def extract_keywords(question):
    normalized = normalize_text(question)
    words = re.findall(r"\w+", normalized)

    keywords = []

    for word in words:
        if len(word) < 3 or word in STOPWORDS:
            continue

        keywords.extend(TRANSLATIONS.get(word, [word]))

    return list(dict.fromkeys(keywords))


def search_scientific_library(question, limit=8):
    initialize_database()

    keywords = extract_keywords(question)

    if not keywords:
        return []

    conditions = []
    parameters = []

    for keyword in keywords:
        conditions.append("""
            (
                LOWER(COALESCE(title, '')) LIKE ?
                OR LOWER(COALESCE(abstract, '')) LIKE ?
                OR LOWER(COALESCE(category, '')) LIKE ?
                OR LOWER(COALESCE(source, '')) LIKE ?
            )
        """)

        parameters.extend([f"%{keyword}%"] * 4)

    sql = f"""
        SELECT *
        FROM documents
        WHERE {" OR ".join(conditions)}
        ORDER BY id DESC
        LIMIT ?
    """

    parameters.append(limit)

    with get_connection() as conn:
        rows = conn.execute(sql, parameters).fetchall()
        return [dict(row) for row in rows]


def get_scientific_context(question):
    documents = search_scientific_library(question)

    if not documents:
        return {
            "documents": [],
            "context": "",
            "message": "No matching scientific documents found."
        }

    context_parts = []

    with get_connection() as conn:
        for doc in documents:
            findings = conn.execute("""
                SELECT finding_text, evidence_level
                FROM findings
                WHERE document_id = ?
            """, (doc["id"],)).fetchall()

            findings_data = [dict(f) for f in findings]

            context_parts.append(
                f"Document ID: {doc['id']}\n"
                f"Title: {doc['title']}\n"
                f"Source: {doc.get('source') or 'Unknown'}\n"
                f"Review status: "
                f"{doc.get('review_status') or 'Unknown'}\n"
                f"Abstract: "
                f"{doc.get('abstract') or 'Not available'}\n"
                f"Recorded findings: {findings_data}\n"
            )

    return {
        "documents": documents,
        "context": "\n---\n".join(context_parts),
        "message": f"{len(documents)} documents retrieved."
    }
