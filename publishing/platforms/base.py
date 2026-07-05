"""
Clase base abstracta para publicadores de plataformas sociales.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class BasePlatform(ABC):
    name: str = "base"

    @abstractmethod
    def publish_video(
        self,
        video_path: Path,
        caption: str,
        hashtags: list[str],
        thumbnail_path: Optional[Path] = None,
    ) -> str:
        """Publica un video. Retorna el ID del post publicado."""
        ...

    @abstractmethod
    def get_post_metrics(self, post_id: str) -> dict:
        """Obtiene métricas de un post publicado."""
        ...

    @abstractmethod
    def get_comments(self, post_id: str, limit: int = 50) -> list[dict]:
        """Obtiene comentarios recientes de un post."""
        ...

    @abstractmethod
    def reply_comment(self, post_id: str, comment_id: str, text: str) -> bool:
        """Responde a un comentario."""
        ...

    def format_caption(self, caption: str, hashtags: list[str], max_length: int = 2200) -> str:
        """Formatea caption + hashtags respetando límites."""
        # Give each sentence/section its own breathing room
        lines = [l.strip() for l in caption.strip().splitlines() if l.strip()]
        spaced = "\n\n".join(lines)

        cta_line = '💬 Comment "REBORN" if you want to know more.'
        tags_text = " ".join(f"#{t.lstrip('#')}" for t in hashtags)

        full = f"{spaced}\n\n{cta_line}\n\n{tags_text}"
        if len(full) > max_length:
            full = full[:max_length - 3] + "..."
        return full
