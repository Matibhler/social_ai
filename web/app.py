"""
Aplicación FastAPI — Interfaz web local del sistema Social AI.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.config import settings
from core.database import get_db, init_db
from core.logger import get_logger
from core.models import (
    CompetitorAccount, CompetitorAnalysis, ContentPiece,
    ContentStatus, Platform, ScheduledPost, Comment,
)
from publishing.scheduler import scheduler

log = get_logger(__name__)

# In-memory progress tracker: {content_id: {"pct": 0-100, "message": "..."}}
_video_progress: dict[int, dict] = {}

# Instagram publish status: {content_id: {"status": "...", "message": "...", "post_id": "..."}}
_instagram_status: dict[int, dict] = {}

def _set_progress(content_id: int, pct: int, message: str):
    _video_progress[content_id] = {"pct": pct, "message": message}

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.start()
    log.info("Social AI iniciado en http://%s:%d", settings.WEB_HOST, settings.WEB_PORT)
    yield
    scheduler.stop()


app = FastAPI(
    title="Social AI — Automatización Local",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Modelos Pydantic ──────────────────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    username: str
    platform: str
    max_posts: int = 20
    niche: Optional[str] = None

class ScriptRequest(BaseModel):
    topic: str
    format: str = "tutorial"
    platform: str = "instagram"
    duration: int = 45

class ScheduleRequest(BaseModel):
    content_id: int
    platform: str
    scheduled_at: datetime
    caption: Optional[str] = None
    hashtags: Optional[list[str]] = []

class CommentApprovalRequest(BaseModel):
    comment_id: int


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    from publishing.queue_manager import get_queue_summary
    from core.llm import llm

    queue = get_queue_summary()
    total_content = db.query(ContentPiece).count()
    total_competitors = db.query(CompetitorAccount).count()
    pending_comments = db.query(Comment).filter_by(requires_response=True, responded=False).count()
    ai_status = "online" if llm.health_check() else "offline"

    return templates.TemplateResponse(request, "dashboard.html", {
        "queue": queue,
        "total_content": total_content,
        "total_competitors": total_competitors,
        "pending_comments": pending_comments,
        "ai_status": ai_status,
        "brand_name": settings.BRAND_NAME,
        "niche": settings.NICHE,
    })


# ── Research ──────────────────────────────────────────────────────────────────

@app.get("/research", response_class=HTMLResponse)
async def research_page(request: Request, db: Session = Depends(get_db)):
    accounts = db.query(CompetitorAccount).order_by(
        CompetitorAccount.last_analyzed.desc()
    ).limit(20).all()
    return templates.TemplateResponse(request, "research.html", {"accounts": accounts})


@app.post("/api/research/scrape")
async def start_scrape(req: ScrapeRequest, bg: BackgroundTasks):
    bg.add_task(_scrape_task, req.username, req.platform, req.max_posts, req.niche)
    return {"status": "started", "message": f"Scraping @{req.username} en background"}


@app.post("/api/research/analyze/{account_id}")
async def analyze_account(account_id: int, bg: BackgroundTasks):
    bg.add_task(_analyze_task, account_id)
    return {"status": "started", "message": f"Analizando cuenta {account_id}"}


@app.get("/api/research/report/{account_id}")
async def get_report(account_id: int):
    from research.reporter import generate_html_report
    report_path = await asyncio.to_thread(generate_html_report, account_id)
    return FileResponse(str(report_path), media_type="text/html")


@app.get("/api/research/opportunities")
async def get_opportunities():
    from research.analyzer import find_content_opportunities
    opportunities = await asyncio.to_thread(find_content_opportunities, settings.NICHE)
    return {"opportunities": opportunities}


# ── Content ───────────────────────────────────────────────────────────────────

@app.get("/content", response_class=HTMLResponse)
async def content_page(request: Request, db: Session = Depends(get_db)):
    pieces = db.query(ContentPiece).order_by(ContentPiece.created_at.desc()).limit(20).all()
    return templates.TemplateResponse(request, "content.html", {"pieces": pieces})


@app.post("/api/content/generate-script")
async def generate_script(req: ScriptRequest):
    from content.script_generator import generate_script as _gen
    try:
        piece = await asyncio.to_thread(
            _gen,
            topic=req.topic,
            format=req.format,
            platform=Platform(req.platform),
            target_duration=req.duration,
        )
    except Exception as e:
        log.error("Error generando guión: %s", e)
        raise HTTPException(500, detail=str(e))
    return {"id": piece.id, "title": piece.title, "script": piece.script, "hook": piece.hook}


@app.post("/api/content/suggest-topics")
async def suggest_topics():
    from content.script_generator import suggest_topics as _suggest
    try:
        topics = await asyncio.to_thread(_suggest, settings.NICHE, 10)
    except Exception as e:
        log.error("Error sugiriendo temas: %s", e)
        return {"topics": []}
    return {"topics": topics}


@app.post("/api/content/{content_id}/produce")
async def produce_video(content_id: int, bg: BackgroundTasks):
    bg.add_task(_produce_video_task, content_id)
    return {"status": "started", "message": f"Produciendo video para contenido {content_id}"}


@app.get("/api/content/{content_id}")
async def get_content(content_id: int, db: Session = Depends(get_db)):
    piece = db.get(ContentPiece, content_id)
    if not piece:
        raise HTTPException(404, "Contenido no encontrado")
    return {
        "id": piece.id, "title": piece.title, "script": piece.script,
        "hook": piece.hook,
        "status": piece.status, "video_path": piece.video_path,
        "hashtags": piece.hashtags,
    }


@app.delete("/api/content/{content_id}")
async def delete_content(content_id: int, db: Session = Depends(get_db)):
    piece = db.get(ContentPiece, content_id)
    if not piece:
        raise HTTPException(404, "Contenido no encontrado")
    import shutil
    export_dir = settings.EXPORTS_DIR / f"content_{content_id}"
    if export_dir.exists():
        shutil.rmtree(export_dir, ignore_errors=True)
    db.delete(piece)
    db.commit()
    return {"ok": True}


@app.get("/api/content/{content_id}/progress")
async def get_video_progress(content_id: int, db: Session = Depends(get_db)):
    prog = _video_progress.get(content_id)
    if prog:
        return prog
    # If no active progress, check DB status
    piece = db.get(ContentPiece, content_id)
    if piece and piece.status == ContentStatus.QUEUED:
        return {"pct": 100, "message": "Video listo"}
    if piece and piece.status.value == "failed":
        return {"pct": -1, "message": "Error al producir video"}
    return {"pct": 0, "message": "Esperando..."}


# ── Publishing ────────────────────────────────────────────────────────────────

@app.get("/publishing", response_class=HTMLResponse)
async def publishing_page(request: Request, db: Session = Depends(get_db)):
    from publishing.queue_manager import get_queue_summary
    queue = get_queue_summary()
    scheduled = (
        db.query(ScheduledPost)
        .filter_by(status=ContentStatus.QUEUED)
        .order_by(ScheduledPost.scheduled_at.asc())
        .limit(20)
        .all()
    )
    return templates.TemplateResponse(request, "publishing.html", {"queue": queue, "scheduled": scheduled})


@app.post("/api/publishing/schedule")
async def schedule_post(req: ScheduleRequest):
    from publishing.queue_manager import add_to_queue
    sp = add_to_queue(
        content_id=req.content_id,
        platform=Platform(req.platform),
        scheduled_at=req.scheduled_at,
        caption=req.caption,
        hashtags=req.hashtags,
    )
    scheduler.schedule_post(sp.id, req.scheduled_at)
    return {"id": sp.id, "scheduled_at": sp.scheduled_at.isoformat()}


# ── Instagram ─────────────────────────────────────────────────────────────────

@app.get("/api/instagram/config")
async def instagram_config():
    configured = bool(settings.INSTAGRAM_ACCESS_TOKEN and settings.INSTAGRAM_ACCOUNT_ID)
    return {"configured": configured, "account_id": settings.INSTAGRAM_ACCOUNT_ID or None}


@app.post("/api/content/{content_id}/publish/instagram")
async def publish_to_instagram(content_id: int, bg: BackgroundTasks, db: Session = Depends(get_db)):
    if not settings.INSTAGRAM_ACCESS_TOKEN or not settings.INSTAGRAM_ACCOUNT_ID:
        raise HTTPException(400, "Instagram no configurado. Agrega INSTAGRAM_ACCESS_TOKEN e INSTAGRAM_ACCOUNT_ID en el archivo .env")
    piece = db.get(ContentPiece, content_id)
    if not piece:
        raise HTTPException(404, "Contenido no encontrado")
    if not piece.video_path:
        raise HTTPException(400, "Este contenido no tiene video. Produce el video primero.")
    _instagram_status[content_id] = {"status": "starting", "message": "Iniciando publicación..."}
    bg.add_task(_publish_instagram_task, content_id)
    return {"status": "started"}


@app.get("/api/content/{content_id}/instagram-status")
async def get_instagram_publish_status(content_id: int):
    return _instagram_status.get(content_id, {"status": "idle"})


# ── Engagement ─────────────────────────────────────────────────────────────────

@app.get("/engagement", response_class=HTMLResponse)
async def engagement_page(request: Request, db: Session = Depends(get_db)):
    pending_comments = (
        db.query(Comment)
        .filter_by(requires_response=True, responded=False)
        .order_by(Comment.likes.desc())
        .limit(20)
        .all()
    )
    return templates.TemplateResponse(request, "engagement.html", {"comments": pending_comments})


@app.post("/api/engagement/fetch-comments")
async def fetch_comments(bg: BackgroundTasks):
    bg.add_task(_fetch_comments_task)
    return {"status": "started"}


@app.post("/api/engagement/generate-responses")
async def generate_responses(bg: BackgroundTasks):
    bg.add_task(_generate_responses_task)
    return {"status": "started"}


@app.post("/api/engagement/approve-comment")
async def approve_comment(req: CommentApprovalRequest):
    from engagement.response_generator import approve_and_publish
    success = approve_and_publish(req.comment_id)
    return {"success": success}


# ── Background tasks ──────────────────────────────────────────────────────────

async def _scrape_task(username: str, platform_str: str, max_posts: int, niche: str):
    import asyncio
    from research.scraper import SocialScraper, save_scrape_results
    platform = Platform(platform_str)
    niche = niche or settings.NICHE

    async with SocialScraper() as scraper:
        if platform == Platform.INSTAGRAM:
            posts, followers = await scraper.scrape_instagram_profile(username, max_posts)
        elif platform == Platform.TIKTOK:
            posts, followers = await scraper.scrape_tiktok_profile(username, max_posts)
        else:
            log.warning("Plataforma de scraping no soportada: %s", platform)
            return

    save_scrape_results(username, platform, posts, followers, niche)


def _analyze_task(account_id: int):
    from research.analyzer import analyze_account
    analyze_account(account_id)


def _produce_video_task(content_id: int):
    """Pipeline cinematografico completo de produccion de video."""
    from core.database import get_session
    from core.models import ContentPiece
    from content.media_downloader import MediaDownloader
    from content.tts_engine import TTSEngine
    from content.subtitle_generator import transcribe_audio, to_ass
    from content.video_editor import VideoEditor
    import random, re

    with get_session() as db:
        piece = db.get(ContentPiece, content_id)
        if not piece:
            return

        base = settings.EXPORTS_DIR / f"content_{content_id}"
        base.mkdir(parents=True, exist_ok=True)

        try:
            _set_progress(content_id, 10, "Buscando clips cinematográficos...")

            # 1. Descargar 2-3 clips cinematográficos únicos
            from content.script_generator import get_clip_keywords
            keywords = get_clip_keywords(n_clips=3)
            log.info("Keywords B-roll: %s", keywords)
            downloader = MediaDownloader()
            clips = downloader.download_batch(keywords, content_id, max_per_query=1)
            _set_progress(content_id, 50, "Renderizando video...")

            # 2. Música de fondo desde data/music/
            music_path = None
            music_dir = settings.DATA_DIR / "music"
            if music_dir.exists():
                music_files = [
                    f for f in music_dir.iterdir()
                    if f.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg")
                ]
                if music_files:
                    music_path = random.choice(music_files)

            # 3. Pipeline silencioso: clips + párrafo emocional + música (sin voz, sin subtítulos)
            video_path = base / "final.mp4"
            hook_display = (piece.hook or piece.title or "")[:180]
            VideoEditor().silent_pipeline(
                clips=clips,
                hook_text=hook_display,
                output_path=video_path,
                music_path=music_path,
            )
            piece.video_path = str(video_path)
            _set_progress(content_id, 95, "Generando miniatura...")

            # 8. Thumbnail
            thumb_path = base / "thumbnail.jpg"
            VideoEditor().extract_thumbnail(video_path, thumb_path)
            piece.thumbnail_path = str(thumb_path)

            piece.status = ContentStatus.QUEUED
            db.commit()
            _video_progress.pop(content_id, None)
            log.info("Video producido: %s", video_path)

        except Exception as e:
            log.error("Error produciendo video %d: %s", content_id, e)
            _set_progress(content_id, -1, f"Error: {e}")
            piece.status = ContentStatus.FAILED
            db.commit()


def _fetch_comments_task():
    from engagement.comment_monitor import fetch_new_comments, classify_comments
    count = fetch_new_comments()
    classified = classify_comments(batch_size=50)
    log.info("Ciclo de comentarios: %d nuevos, %d clasificados", count, classified)


def _generate_responses_task():
    from engagement.response_generator import batch_generate_responses
    results = batch_generate_responses(limit=10, auto_approve=False)
    log.info("Respuestas generadas: %d", len(results))


def _publish_instagram_task(content_id: int):
    import json as _json
    from core.database import get_session
    from publishing.platforms.instagram import InstagramPlatform

    with get_session() as db:
        piece = db.get(ContentPiece, content_id)
        if not piece or not piece.video_path:
            _instagram_status[content_id] = {"status": "error", "message": "Video no encontrado"}
            return
        try:
            _instagram_status[content_id] = {"status": "uploading", "message": "Subiendo video a Instagram..."}
            ig = InstagramPlatform()

            # hashtags may be stored as a JSON string — parse it
            raw_tags = piece.hashtags or []
            if isinstance(raw_tags, str):
                try:
                    raw_tags = _json.loads(raw_tags)
                except Exception:
                    raw_tags = []

            post_id = ig.publish_video(
                video_path=Path(piece.video_path),
                caption=piece.hook or piece.title or "",
                hashtags=raw_tags,
            )
            piece.status = ContentStatus.PUBLISHED
            db.commit()
            _instagram_status[content_id] = {"status": "done", "post_id": post_id, "message": "Publicado en Instagram"}
            log.info("Publicado en Instagram: post_id=%s content_id=%d", post_id, content_id)
        except Exception as e:
            log.error("Error publicando en Instagram content_id=%d: %s", content_id, e)
            # extract the actual Meta API error message if available
            msg = str(e)
            try:
                import httpx
                if hasattr(e, 'response') and e.response is not None:
                    meta_error = e.response.json().get("error", {})
                    msg = meta_error.get("message", msg)
            except Exception:
                pass
            _instagram_status[content_id] = {"status": "error", "message": msg}
