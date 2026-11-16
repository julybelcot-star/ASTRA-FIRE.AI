
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY no encontrada en .env"
        )

    return genai.Client(api_key=api_key)


def ask_gemini(question):
    client = get_gemini_client()

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=question
    )

    return response.text or "Sin respuesta de Gemini."

