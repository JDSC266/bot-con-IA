"""
claude_api.py - Integración con Groq API (gratuito)
"""
import logging
from groq import Groq
from config import GROQ_API_KEY, MAX_TOKENS, SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_client = Groq(api_key=GROQ_API_KEY)
GROQ_MODEL = "llama-3.3-70b-versatile"


def get_response(messages: list, user_message: str) -> tuple[str, list]:
    """
    Envía un mensaje a Groq y devuelve (respuesta, historial_actualizado).
    """
    messages = messages + [{"role": "user", "content": user_message}]
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    try:
        response = _client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=MAX_TOKENS,
            messages=full_messages,
        )
        assistant_text = response.choices[0].message.content
        updated_messages = messages + [{"role": "assistant", "content": assistant_text}]
        return assistant_text, updated_messages

    except Exception as e:
        logger.error(f"Error con Groq API: {e}")
        error_msg = str(e).lower()
        if "rate" in error_msg or "quota" in error_msg:
            raise RuntimeError("Demasiadas solicitudes. Por favor espera un momento.") from e
        elif "connection" in error_msg or "network" in error_msg:
            raise RuntimeError("No se pudo conectar con el servicio de IA. Intenta de nuevo.") from e
        elif "invalid api key" in error_msg or "authentication" in error_msg:
            raise RuntimeError("Error de autenticación con el servicio de IA.") from e
        else:
            raise RuntimeError("Error inesperado al procesar tu mensaje.") from e
