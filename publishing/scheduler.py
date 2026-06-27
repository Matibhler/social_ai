"""
Programador de publicaciones usando APScheduler.
Gestiona la cola de contenido y ejecuta publicaciones en el horario configurado.
"""

from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from core.database import get_session
from core.logger import get_logger
from core.models import ContentPiece, ContentStatus, Platform, ScheduledPost
from publishing.queue_manager import get_next_queued

log = get_logger(__name__)


def _get_platform_publisher(platform: Platform):
    """Factory para obtener el publicador correcto según la plataforma."""
    from publishing.platforms.instagram import InstagramPlatform
    from publishing.platforms.youtube import YouTubePlatform

    publishers = {
        Platform.INSTAGRAM: InstagramPlatform,
        Platform.YOUTUBE: YouTubePlatform,
    }
    cls = publishers.get(platform)
    if not cls:
        raise ValueError(f"Plataforma no soportada: {platform}")
    return cls()


def publish_scheduled_post(scheduled_post_id: int):
    """Ejecuta la publicación de un post programado."""
    with get_session() as db:
        sp = db.get(ScheduledPost, scheduled_post_id)
        if not sp:
            log.error("ScheduledPost %d no encontrado", scheduled_post_id)
            return

        content = db.get(ContentPiece, sp.content_id)
        if not content or not content.video_path:
            log.error("Contenido o video no disponible para post %d", scheduled_post_id)
            sp.status = ContentStatus.FAILED
            sp.error_message = "Video no disponible"
            db.commit()
            return

        try:
            publisher = _get_platform_publisher(sp.platform)
            post_id = publisher.publish_video(
                video_path=Path(content.video_path),
                caption=sp.caption or content.script[:300],
                hashtags=sp.hashtags or content.hashtags or [],
                thumbnail_path=Path(content.thumbnail_path) if content.thumbnail_path else None,
            )
            sp.platform_post_id = post_id
            sp.published_at = datetime.utcnow()
            sp.status = ContentStatus.PUBLISHED
            content.status = ContentStatus.PUBLISHED
            log.info("Post %d publicado en %s: %s", scheduled_post_id, sp.platform, post_id)
        except Exception as e:
            sp.status = ContentStatus.FAILED
            sp.error_message = str(e)
            log.error("Error publicando post %d: %s", scheduled_post_id, e)
        finally:
            db.commit()


class ContentScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler(timezone="America/Mexico_City")

    def start(self):
        # Verificar cola cada 5 minutos
        self.scheduler.add_job(
            self._check_and_publish,
            CronTrigger(minute="*/5"),
            id="queue_checker",
            replace_existing=True,
        )
        # Actualizar métricas cada 6 horas
        self.scheduler.add_job(
            self._update_metrics,
            CronTrigger(hour="*/6"),
            id="metrics_updater",
            replace_existing=True,
        )
        self.scheduler.start()
        log.info("Scheduler iniciado")

    def stop(self):
        self.scheduler.shutdown(wait=False)
        log.info("Scheduler detenido")

    def schedule_post(self, scheduled_post_id: int, publish_at: datetime):
        """Programa un post para publicarse en una fecha/hora específica."""
        job_id = f"post_{scheduled_post_id}"
        self.scheduler.add_job(
            publish_scheduled_post,
            DateTrigger(run_date=publish_at),
            args=[scheduled_post_id],
            id=job_id,
            replace_existing=True,
        )
        log.info("Post %d programado para %s", scheduled_post_id, publish_at)

    def _check_and_publish(self):
        """Verifica si hay posts programados para publicar ahora."""
        now = datetime.utcnow()
        with get_session() as db:
            due_posts = (
                db.query(ScheduledPost)
                .filter(
                    ScheduledPost.status == ContentStatus.QUEUED,
                    ScheduledPost.scheduled_at <= now,
                )
                .all()
            )
            for sp in due_posts:
                log.info("Publicando post programado: %d", sp.id)
                publish_scheduled_post(sp.id)

    def _update_metrics(self):
        """Actualiza métricas de posts publicados recientemente."""
        with get_session() as db:
            recent = (
                db.query(ScheduledPost)
                .filter_by(status=ContentStatus.PUBLISHED)
                .filter(ScheduledPost.platform_post_id.isnot(None))
                .limit(20)
                .all()
            )
            for sp in recent:
                try:
                    publisher = _get_platform_publisher(sp.platform)
                    metrics = publisher.get_post_metrics(sp.platform_post_id)
                    sp.metrics = metrics
                except Exception as e:
                    log.warning("Error actualizando métricas para post %s: %s", sp.id, e)
            db.commit()


scheduler = ContentScheduler()
