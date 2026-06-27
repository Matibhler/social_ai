"""
Generador de respuestas a comentarios y mensajes usando LLM.
Modo semiautomático: genera, muestra preview y espera aprobación.
"""

from core.config import settings
from core.database import get_session
from core.llm import llm
from core.logger import get_logger
from core.models import Comment

log = get_logger(__name__)

RESPONSE_SYSTEM = f"""
Eres el community manager de {settings.BRAND_NAME}.
Voz de marca: {settings.BRAND_VOICE}
Nicho: {settings.NICHE}

Reglas:
- Respuestas cortas, naturales y auténticas (máx 3 oraciones)
- No uses emojis en exceso (máx 2 por respuesta)
- Responde en el mismo idioma del comentario
- Si es una pregunta, respóndela directamente
- Nunca uses respuestas genéricas como "¡Gracias por tu comentario!"
- Personaliza usando el texto del comentario
"""


def generate_response(comment: Comment, auto_approve: bool = False) -> str:
    """
    Genera una respuesta para un comentario.
    Si auto_approve=False, solo guarda el borrador y espera aprobación.
    """
    prompt = f"""
Comentario recibido en {comment.platform} (sentimiento: {comment.sentiment}):
"{comment.text}"

Genera una respuesta natural para {settings.BRAND_NAME}.
Devuelve solo el texto de la respuesta, sin comillas ni explicaciones.
"""
    response_text = llm.generate(prompt, system=RESPONSE_SYSTEM).strip()

    with get_session() as db:
        db_comment = db.get(Comment, comment.id)
        db_comment.response_text = response_text
        db_comment.response_approved = auto_approve
        if auto_approve:
            db_comment.responded = True
        db.commit()

    log.info(
        "Respuesta generada para comentario %d (%s)",
        comment.id,
        "auto-aprobada" if auto_approve else "pendiente de aprobación",
    )
    return response_text


def approve_and_publish(comment_id: int) -> bool:
    """Aprueba una respuesta y la publica."""
    from publishing.platforms.instagram import InstagramPlatform
    from publishing.platforms.youtube import YouTubePlatform
    from core.models import Platform

    with get_session() as db:
        comment = db.get(Comment, comment_id)
        if not comment or not comment.response_text:
            log.error("Comentario %d sin respuesta generada", comment_id)
            return False

        publishers = {
            Platform.INSTAGRAM: InstagramPlatform(),
            Platform.YOUTUBE: YouTubePlatform(),
        }
        publisher = publishers.get(comment.platform)
        if not publisher:
            return False

        success = publisher.reply_comment(
            post_id=comment.post_id,
            comment_id=comment.comment_id,
            text=comment.response_text,
        )
        if success:
            comment.responded = True
            comment.response_approved = True
        db.commit()
        return success


def batch_generate_responses(limit: int = 10, auto_approve: bool = False) -> list[dict]:
    """Genera respuestas para los comentarios pendientes."""
    from engagement.comment_monitor import get_comments_needing_response

    pending = get_comments_needing_response(limit=limit)
    results = []

    for comment in pending:
        try:
            text = generate_response(comment, auto_approve=auto_approve)
            results.append({
                "comment_id": comment.id,
                "original": comment.text,
                "response": text,
                "approved": auto_approve,
            })
        except Exception as e:
            log.error("Error generando respuesta para comentario %d: %s", comment.id, e)

    return results


def generate_dm_response(thread_id: str, last_message: str, context_summary: str) -> str:
    """Genera respuesta para un mensaje directo."""
    prompt = f"""
Contexto de la conversación:
{context_summary}

Último mensaje recibido:
"{last_message}"

Genera una respuesta de mensaje directo para {settings.BRAND_NAME}.
Máximo 2-3 oraciones. Natural, personalizada, sin ser vendedor agresivo.
"""
    return llm.generate(prompt, system=RESPONSE_SYSTEM).strip()
