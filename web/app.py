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
    piece = await asyncio.to_thread(
        _gen,
        topic=req.topic,
        format=req.format,
        platform=Platform(req.platform),
        target_duration=req.duration,
    )
    return {"id": piece.id, "title": piece.title, "script": piece.script}


@app.post("/api/content/suggest-topics")
async def suggest_topics():
    from content.script_generator import suggest_topics as _suggest
    topics = await asyncio.to_thread(_suggest, settings.NICHE, 10)
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
        "status": piece.status, "video_path": piece.video_path,
        "hashtags": piece.hashtags,
    }


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


# ── Engagement ────────────────────────────────────────────────────────────────

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
    """Pipeline completo de producción de video."""
    from core.database import get_session
    from core.models import ContentPiece
    from content.media_downloader import MediaDownloader
    from content.tts_engine import TTSEngine
    from content.subtitle_generator import transcribe_audio, to_ass
    from content.video_editor import VideoEditor
    import re

    with get_session() as db:
        piece = db.get(ContentPiece, content_id)
        if not piece:
            return

        base = settings.EXPORTS_DIR / f"content_{content_id}"
        base.mkdir(parents=True, exist_ok=True)

        try:
            # 1. TTS
            audio_path = base / "narration.mp3"
            tts = TTSEngine()
            tts.synthesize(piece.script, audio_path)
            piece.audio_path = str(audio_path)

            # 2. Subtítulos
            segments = transcribe_audio(audio_path)
            sub_path = base / "subtitles.ass"
            to_ass(segments, sub_path, style="viral")
            piece.subtitle_path = str(sub_path)

            # 3. Descargar media
            keywords = re.findall(r'\b\w{5,}\b', piece.title)[:3]
            downloader = MediaDownloader()
            clips = downloader.download_batch(keywords, content_id, max_per_query=2)

            # 4. Renderizar video
            video_path = base / "final.mp4"
            VideoEditor().full_pipeline(
                clips=clips,
                audio_path=audio_path,
                subtitle_path=sub_path,
                hook_text=piece.hook or piece.title,
                output_path=video_path,
            )
            piece.video_path = str(video_path)

            # 5. Thumbnail
            thumb_path = base / "thumbnail.jpg"
            VideoEditor().extract_thumbnail(video_path, thumb_path)
            piece.thumbnail_path = str(thumb_path)

            piece.status = ContentStatus.QUEUED
            db.commit()
            log.info("Video producido: %s", video_path)

        except Exception as e:
            log.error("Error produciendo video %d: %s", content_id, e)
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
