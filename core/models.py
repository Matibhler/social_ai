"""
Modelos de base de datos (SQLAlchemy ORM).
"""

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Integer, JSON, String, Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ── Enums ─────────────────────────────────────────────────────────────────────

class Platform(str, PyEnum):
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    FACEBOOK = "facebook"


class ContentStatus(str, PyEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    PUBLISHED = "published"
    FAILED = "failed"


class TaskStatus(str, PyEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


# ── Modelos ───────────────────────────────────────────────────────────────────

class CompetitorAccount(Base):
    __tablename__ = "competitor_accounts"

    id = Column(Integer, primary_key=True)
    platform = Column(Enum(Platform), nullable=False)
    username = Column(String(100), nullable=False)
    display_name = Column(String(200))
    followers = Column(Integer, default=0)
    niche = Column(String(100))
    last_analyzed = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    posts = relationship("CompetitorPost", back_populates="account")
    analysis = relationship("CompetitorAnalysis", back_populates="account")


class CompetitorPost(Base):
    __tablename__ = "competitor_posts"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("competitor_accounts.id"))
    platform = Column(Enum(Platform))
    post_id = Column(String(200))
    url = Column(String(500))
    caption = Column(Text)
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    duration_seconds = Column(Integer)
    hook_text = Column(Text)         # primeros 3 segundos / primera línea
    cta_text = Column(Text)          # llamado a la acción detectado
    content_format = Column(String(50))  # tutorial, list, story, etc.
    hashtags = Column(JSON)
    published_at = Column(DateTime)
    scraped_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("CompetitorAccount", back_populates="posts")


class CompetitorAnalysis(Base):
    __tablename__ = "competitor_analysis"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("competitor_accounts.id"))
    analyzed_at = Column(DateTime, default=datetime.utcnow)
    top_formats = Column(JSON)
    avg_duration = Column(Float)
    posting_frequency_per_week = Column(Float)
    best_posting_hours = Column(JSON)
    common_hooks = Column(JSON)
    common_ctas = Column(JSON)
    top_hashtags = Column(JSON)
    content_gaps = Column(JSON)    # oportunidades detectadas
    report_path = Column(String(500))

    account = relationship("CompetitorAccount", back_populates="analysis")


class ContentPiece(Base):
    __tablename__ = "content_pieces"

    id = Column(Integer, primary_key=True)
    title = Column(String(300))
    script = Column(Text)
    hook = Column(Text)
    cta = Column(Text)
    niche = Column(String(100))
    format = Column(String(50))
    target_platform = Column(Enum(Platform))
    status = Column(Enum(ContentStatus), default=ContentStatus.DRAFT)
    script_path = Column(String(500))
    audio_path = Column(String(500))
    subtitle_path = Column(String(500))
    video_path = Column(String(500))
    thumbnail_path = Column(String(500))
    hashtags = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    scheduled_posts = relationship("ScheduledPost", back_populates="content")
    media_assets = relationship("MediaAsset", back_populates="content")


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id = Column(Integer, primary_key=True)
    content_id = Column(Integer, ForeignKey("content_pieces.id"))
    source = Column(String(50))      # pexels, pixabay, local
    source_id = Column(String(200))
    url = Column(String(500))
    local_path = Column(String(500))
    asset_type = Column(String(20))  # video, image, audio
    duration = Column(Float)
    width = Column(Integer)
    height = Column(Integer)
    license = Column(String(200))
    downloaded_at = Column(DateTime, default=datetime.utcnow)

    content = relationship("ContentPiece", back_populates="media_assets")


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"

    id = Column(Integer, primary_key=True)
    content_id = Column(Integer, ForeignKey("content_pieces.id"))
    platform = Column(Enum(Platform))
    scheduled_at = Column(DateTime)
    published_at = Column(DateTime)
    platform_post_id = Column(String(200))
    status = Column(Enum(ContentStatus), default=ContentStatus.QUEUED)
    caption = Column(Text)
    hashtags = Column(JSON)
    error_message = Column(Text)
    metrics = Column(JSON)   # views, likes, etc. al momento del registro

    content = relationship("ContentPiece", back_populates="scheduled_posts")


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    platform = Column(Enum(Platform))
    post_id = Column(String(200))
    comment_id = Column(String(200), unique=True)
    author_username = Column(String(100))
    text = Column(Text)
    likes = Column(Integer, default=0)
    sentiment = Column(String(20))   # positive, negative, neutral
    requires_response = Column(Boolean, default=False)
    responded = Column(Boolean, default=False)
    response_text = Column(Text)
    response_approved = Column(Boolean, default=False)
    posted_at = Column(DateTime)
    detected_at = Column(DateTime, default=datetime.utcnow)


class DMConversation(Base):
    __tablename__ = "dm_conversations"

    id = Column(Integer, primary_key=True)
    platform = Column(Enum(Platform))
    thread_id = Column(String(200), unique=True)
    contact_username = Column(String(100))
    contact_display_name = Column(String(200))
    consent_given = Column(Boolean, default=False)  # cumplimiento ético
    context_summary = Column(Text)  # resumen de contexto para el LLM
    lead_status = Column(String(50), default="new")  # new, warm, converted
    created_at = Column(DateTime, default=datetime.utcnow)
    last_message_at = Column(DateTime)

    messages = relationship("DMMessage", back_populates="conversation")


class DMMessage(Base):
    __tablename__ = "dm_messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("dm_conversations.id"))
    direction = Column(String(10))   # inbound | outbound
    text = Column(Text)
    sent_at = Column(DateTime)
    ai_generated = Column(Boolean, default=False)
    approved = Column(Boolean, default=False)

    conversation = relationship("DMConversation", back_populates="messages")


class SystemTask(Base):
    __tablename__ = "system_tasks"

    id = Column(Integer, primary_key=True)
    name = Column(String(200))
    task_type = Column(String(50))
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING)
    payload = Column(JSON)
    result = Column(JSON)
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
