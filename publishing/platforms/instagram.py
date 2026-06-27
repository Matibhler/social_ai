"""
Publicador de Instagram usando la Meta Graph API oficial.
Requiere: Instagram Business / Creator account conectada a una página de Facebook.
"""

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
        self.client = httpx.Client(timeout=120)

    def publish_video(
        self,
        video_path: Path,
        caption: str,
        hashtags: list[str],
        thumbnail_path: Optional[Path] = None,
    ) -> str:
        """
        Publica un Reel en Instagram.
        Flujo: create container → esperar → publish
        """
        full_caption = self.format_caption(caption, hashtags)

        # 1. Subir video a un hosting temporal o usar URL pública
        # La Graph API requiere una URL pública para el video.
        # En producción se puede usar un servidor ngrok local temporal.
        video_url = self._upload_to_temp_server(video_path)

        log.info("Creando contenedor de Reel en Instagram…")
        container_resp = self.client.post(
            f"{GRAPH_URL}/{self.account_id}/media",
            params={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": full_caption,
                "access_token": self.token,
            },
        )
        container_resp.raise_for_status()
        container_id = container_resp.json()["id"]
        log.info("Contenedor creado: %s", container_id)

        # 2. Esperar a que el video sea procesado
        self._wait_for_processing(container_id)

        # 3. Publicar
        publish_resp = self.client.post(
            f"{GRAPH_URL}/{self.account_id}/media_publish",
            params={"creation_id": container_id, "access_token": self.token},
        )
        publish_resp.raise_for_status()
        post_id = publish_resp.json()["id"]
        log.info("Reel publicado: %s", post_id)
        return post_id

    def _wait_for_processing(self, container_id: str, max_attempts: int = 20):
        import time
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

    def _upload_to_temp_server(self, video_path: Path) -> str:
        """
        Sube el video a un servidor local con ngrok para obtener URL pública.
        En producción se recomienda usar S3, R2, o similar.
        """
        # Placeholder: en implementación real usar ngrok o S3
        log.warning(
            "Se requiere URL pública para el video. "
            "Configura un servidor con ngrok o S3."
        )
        return f"https://your-server.com/media/{video_path.name}"

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
