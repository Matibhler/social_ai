"""
Monitor de comentarios. Detecta nuevos comentarios y los clasifica
para decidir si requieren respuesta.
"""

from datetime import datetime

from core.database import get_session
from core.llm import llm
from core.logger import get_logger
from core.models import Comment, Platform, ScheduledPost, ContentStatus

log = get_logger(__name__)

CLASSIFY_SYSTEM = """
Eres un moderador de comunidad experto. Analiza comentarios de redes sociales
y determina si requieren respuesta y cuál es su sentimiento.
Responde solo con JSON.
"""


def fetch_new_comments() -> int:
    """Obtiene comentarios nuevos de todos los posts publicados."""
    from publishing.platforms.instagram import InstagramPlatform
    from publishing.platforms.youtube import YouTubePlatform

    publishers = {
        Platform.INSTAGRAM: InstagramPlatform(),
        Platform.YOUTUBE: YouTubePlatform(),
    }

    total_new = 0
    with get_session() as db:
        published_posts = (
            db.query(ScheduledPost)
            .filter_by(status=ContentStatus.PUBLISHED)
            .filter(ScheduledPost.platform_post_id.isnot(None))
            .all()
        )

        for sp in published_posts:
            publisher = publishers.get(sp.platform)
            if not publisher:
                continue
            try:
                comments = publisher.get_comments(sp.platform_post_id, limit=50)
                new_count = _save_new_comments(db, comments, sp.platform, sp.platform_post_id)
                total_new += new_count
            except Exception as e:
                log.warning("Error obteniendo comentarios de %s: %s", sp.platform_post_id, e)

    log.info("Detectados %d comentarios nuevos", total_new)
    return total_new


def _save_new_comments(db, raw_comments: list[dict], platform: Platform, post_id: str) -> int:
    count = 0
    for c in raw_comments:
        comment_id = str(c.get("id", ""))
        existing = db.query(Comment).filter_by(comment_id=comment_id).first()
        if existing:
            continue

        comment = Comment(
            platform=platform,
            post_id=post_id,
            comment_id=comment_id,
            author_username=c.get("author") or c.get("from", {}).get("username", ""),
            text=c.get("text", ""),
            likes=c.get("likes", 0),
            posted_at=_parse_date(c.get("timestamp")),
            detected_at=datetime.utcnow(),
        )
        db.add(comment)
        count += 1
    db.commit()
    return count


def classify_comments(batch_size: int = 20) -> int:
    """Clasifica comentarios pendientes con el LLM."""
    with get_session() as db:
        pending = (
            db.query(Comment)
            .filter(Comment.sentiment.is_(None))
            .limit(batch_size)
            .all()
        )

        if not pending:
            return 0

        for comment in pending:
            try:
                classification = _classify_comment(comment.text)
                comment.sentiment = classification.get("sentiment", "neutral")
                comment.requires_response = classification.get("requires_response", False)
            except Exception as e:
                log.warning("Error clasificando comentario %s: %s", comment.id, e)
                comment.sentiment = "neutral"
                comment.requires_response = False

        db.commit()
        log.info("Clasificados %d comentarios", len(pending))
        return len(pending)


def _classify_comment(text: str) -> dict:
    prompt = f"""
Clasifica este comentario de red social:
"{text}"

Devuelve JSON:
{{
  "sentiment": "positive" | "negative" | "neutral",
  "requires_response": true | false,
  "reason": "breve razón"
}}

requires_response = true si: hace una pregunta, expresa queja, pide información,
o es un comentario muy positivo que merece agradecimiento.
"""
    return llm.json_generate(prompt, system=CLASSIFY_SYSTEM)


def get_comments_needing_response(limit: int = 10) -> list[Comment]:
    with get_session() as db:
        return (
            db.query(Comment)
            .filter_by(requires_response=True, responded=False)
            .order_by(Comment.likes.desc())
            .limit(limit)
            .all()
        )


def _parse_date(date_str) -> datetime:
    if not date_str:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
    except Exception:
        return datetime.utcnow()
