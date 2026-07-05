"""
Publicador de Instagram usando la Meta Graph API oficial.
Requiere: Instagram Business / Creator account conectada a una página de Facebook.
"""

import time
from pathlib import Path
from typing import Optional

import httpx

from core.config import settings
from core.logger import get_logger
from publishing.platforms.base import BasePlatform

log = get_logger(__name__)

GRAPH_URL = "https://graph.facebook.com/v19.0"


class InstagramPlatform(BasePlatform):
    name = "instagram"

    def __init__(self):
        self.token = settings.INSTAGRAM_ACCESS_TOKEN
        self.account_id = settings.INSTAGRAM_ACCOUNT_ID
        self.client = httpx.Client(timeout=300)

    def publish_video(
        self,
        video_path: Path,
        caption: str,
        hashtags: list[str],
        thumbnail_path: Optional[Path] = None,
    ) -> str:
        """
        Publica un Reel en Instagram usando carga resumible (no requiere URL pública).
        Flujo: init container → upload file → esperar procesamiento → publish
        """
        video_path = Path(video_path)
        full_caption = self.format_caption(caption, hashtags)
        container_id = self._resumable_upload(video_path, full_caption)
        self._wait_for_processing(container_id)

        publish_resp = self.client.post(
            f"{GRAPH_URL}/{self.account_id}/media_publish",
            params={"creation_id": container_id, "access_token": self.token},
        )
        publish_resp.raise_for_status()
        post_id = publish_resp.json()["id"]
        log.info("Reel publicado: %s", post_id)
        return post_id

    def _resumable_upload(self, video_path: Path, caption: str) -> str:
        """Carga el video directamente a Meta usando el protocolo de carga resumible."""
        file_size = video_path.stat().st_size

        # 1. Inicializar sesión de carga
        init_resp = self.client.post(
            f"{GRAPH_URL}/{self.account_id}/media",
            params={
                "media_type": "REELS",
                "upload_type": "resumable",
                "caption": caption,
                "access_token": self.token,
            },
        )
        if not init_resp.is_success:
            log.error("Meta API error: %s", init_resp.text)
        init_resp.raise_for_status()
        data = init_resp.json()
        container_id = data["id"]
        upload_uri = data["uri"]
        log.info("Sesión de carga iniciada: %s", container_id)

        # 2. Subir el archivo de video
        with open(video_path, "rb") as f:
            video_bytes = f.read()

        upload_resp = self.client.post(
            upload_uri,
            headers={
                "Authorization": f"OAuth {self.token}",
                "offset": "0",
                "file_size": str(file_size),
                "Content-Type": "video/mp4",
            },
            content=video_bytes,
        )
        upload_resp.raise_for_status()
        log.info("Video subido correctamente (%d MB)", file_size // 1_000_000)
        return container_id

    def _wait_for_processing(self, container_id: str, max_attempts: int = 30):
        for attempt in range(max_attempts):
            resp = self.client.get(
                f"{GRAPH_URL}/{container_id}",
                params={
                    "fields": "status_code,status",
                    "access_token": self.token,
                },
            )
            data = resp.json()
            status = data.get("status_code", "")
            log.debug("Estado del contenedor [%d]: %s", attempt, status)
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise RuntimeError(f"Error procesando video: {data.get('status')}")
            time.sleep(10)
        raise TimeoutError("Video no procesado en tiempo esperado")

    def get_post_metrics(self, post_id: str) -> dict:
        resp = self.client.get(
            f"{GRAPH_URL}/{post_id}/insights",
            params={
                "metric": "views,likes_count,comments_count,shares",
                "access_token": self.token,
            },
        )
        if resp.status_code != 200:
            return {}
        data = resp.json().get("data", [])
        return {item["name"]: item["values"][0]["value"] for item in data}

    def get_comments(self, post_id: str, limit: int = 50) -> list[dict]:
        resp = self.client.get(
            f"{GRAPH_URL}/{post_id}/comments",
            params={
                "fields": "id,text,from,timestamp,like_count",
                "limit": limit,
                "access_token": self.token,
            },
        )
        if resp.status_code != 200:
            return []
        return resp.json().get("data", [])

    def reply_comment(self, post_id: str, comment_id: str, text: str) -> bool:
        resp = self.client.post(
            f"{GRAPH_URL}/{comment_id}/replies",
            params={"message": text, "access_token": self.token},
        )
        success = resp.status_code == 200
        if success:
            log.info("Respuesta publicada en comentario %s", comment_id)
        else:
            log.error("Error respondiendo comentario: %s", resp.text)
        return success
