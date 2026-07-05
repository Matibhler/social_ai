"""
Gestión de la cola de contenido listo para publicar.
"""

from datetime import datetime, timedelta
from typing import Optional

from core.database import get_session
from core.logger import get_logger
from core.models import ContentPiece, ContentStatus, Platform, ScheduledPost

log = get_logger(__name__)


def add_to_queue(
    content_id: int,
    platform: Platform,
    scheduled_at: datetime,
    caption: Optional[str] = None,
    hashtags: Optional[list] = None,
) -> ScheduledPost:
    """Agrega un contenido a la cola de publicación."""
    with get_session() as db:
        sp = ScheduledPost(
            content_id=content_id,
            platform=platform,
            scheduled_at=scheduled_at,
            status=ContentStatus.QUEUED,
            caption=caption,
            hashtags=hashtags or [],
        )
        db.add(sp)
        db.commit()
        db.refresh(sp)
        db.expunge(sp)
        log.info(
            "Contenido %d encolado para %s el %s",
            content_id,
            platform,
            scheduled_at.strftime("%Y-%m-%d %H:%M"),
        )
        return sp


def get_next_queued(platform: Optional[Platform] = None) -> Optional[ScheduledPost]:
    """Obtiene el próximo post en cola."""
    with get_session() as db:
        q = db.query(ScheduledPost).filter_by(status=ContentStatus.QUEUED)
        if platform:
            q = q.filter_by(platform=platform)
        return q.order_by(ScheduledPost.scheduled_at.asc()).first()


def get_queue_summary() -> dict:
    """Resumen del estado de la cola."""
    with get_session() as db:
        total = db.query(ScheduledPost).count()
        queued = db.query(ScheduledPost).filter_by(status=ContentStatus.QUEUED).count()
        published = db.query(ScheduledPost).filter_by(status=ContentStatus.PUBLISHED).count()
        failed = db.query(ScheduledPost).filter_by(status=ContentStatus.FAILED).count()

        upcoming = (
            db.query(ScheduledPost)
            .filter(
                ScheduledPost.status == ContentStatus.QUEUED,
                ScheduledPost.scheduled_at >= datetime.utcnow(),
            )
            .order_by(ScheduledPost.scheduled_at.asc())
            .limit(5)
            .all()
        )

        return {
            "total": total,
            "queued": queued,
            "published": published,
            "failed": failed,
            "upcoming": [
                {
                    "id": sp.id,
                    "platform": sp.platform,
                    "scheduled_at": sp.scheduled_at.isoformat(),
                }
                for sp in upcoming
            ],
        }


def auto_schedule_week(
    content_ids: list[int],
    platforms: list[Platform],
    posts_per_day: int = 1,
    best_hours: list[int] | None = None,
) -> list[ScheduledPost]:
    """
    Distribuye contenido a lo largo de la semana en los mejores horarios.
    best_hours: horas preferidas para publicar (ej: [18, 19, 20])
    """
    hours = best_hours or [18, 19, 20]
    scheduled = []
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    slot = now + timedelta(hours=1)

    for i, content_id in enumerate(content_ids):
        for platform in platforms:
            # Calcular slot de tiempo
            day_offset = i // posts_per_day
            hour = hours[i % len(hours)]
            publish_at = (now + timedelta(days=day_offset)).replace(hour=hour)
            if publish_at <= now:
                publish_at += timedelta(days=1)

            sp = add_to_queue(content_id, platform, publish_at)
            scheduled.append(sp)

    log.info("Programados %d posts para la semana", len(scheduled))
    return scheduled
