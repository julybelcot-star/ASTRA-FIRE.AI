
from services.gemini_service import ask_gemini
from services.scientific_search import get_scientific_context


def ask_scientific_assistant(question):
    """
    Scientific AI Assistant for ASTRA-FIRE AI V2.

    All responses must be written in English.
    """

    if not question or not question.strip():
        return {
            "answer": "Please enter a scientific question.",
            "sources": []
        }

    result = get_scientific_context(question)

    documents = result["documents"]
    context = result["context"]

    if not documents:
        return {
            "answer": (
                "No matching scientific documents were found "
                "in the ASTRA-FIRE AI scientific database. "
                "Please try different scientific keywords."
            ),
            "sources": []
        }

    prompt = f"""
You are ASTRA-FIRE AI V2, an advanced scientific
research assistant specializing in combustion
science, fire safety, and microgravity research.

MANDATORY LANGUAGE POLICY:

- Always respond in English (US English).
- Never respond in Spanish.
- This rule applies even if the question is in Spanish.
- Use professional scientific terminology.
- Preserve original document titles.

SCIENTIFIC INTEGRITY RULES:

1. Use the provided scientific database context
   for claims about the document collection.

2. Never fabricate experimental results,
   measurements, values, or conclusions.

3. Clearly distinguish document metadata
   from verified scientific evidence.

4. Never assume that a document supports a
   scientific conclusion based only on its title.

5. Cite document IDs and original titles.

6. If evidence is insufficient, explicitly
   explain the limitation.

7. Do not invent scientific references.

8. Distinguish unreviewed documents from
   scientifically validated information.

9. Never claim to have read a full document
   when only its metadata is available.

USER QUESTION:
{question}

SCIENTIFIC DATABASE CONTEXT:
{context}

REQUIRED RESPONSE FORMAT:

## Scientific Analysis
Provide a clear answer in English.

## Relevant Scientific Documents
Identify relevant document IDs and titles.

## Evidence Assessment
Explain what evidence is actually available.

## Scientific Limitations
Explain missing or unverified information.

FINAL REQUIREMENT:
The entire response must be in English.
"""

    answer = ask_gemini(prompt)

    return {
        "answer": answer,
        "sources": documents
    }
