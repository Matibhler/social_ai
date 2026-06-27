"""
Publicador de YouTube usando YouTube Data API v3.
Publica videos como YouTube Shorts (verticales <60 segundos).
"""

import os
from pathlib import Path
from typing import Optional

from core.config import settings
from core.logger import get_logger
from publishing.platforms.base import BasePlatform

log = get_logger(__name__)


class YouTubePlatform(BasePlatform):
    name = "youtube"

    def __init__(self):
        self._service = None

    def _get_service(self):
        if self._service:
            return self._service
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
                      "https://www.googleapis.com/auth/youtube.force-ssl"]

            creds = None
            token_path = Path(settings.BASE_DIR) / "youtube_token.json"
            if token_path.exists():
                creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

            if not creds or not creds.valid:
                flow = InstalledAppFlow.from_client_secrets_file(
                    settings.YOUTUBE_CLIENT_SECRETS, SCOPES
                )
                creds = flow.run_local_server(port=0)
                token_path.write_text(creds.to_json())

            self._service = build("youtube", "v3", credentials=creds)
            return self._service
        except ImportError:
            raise ImportError(
                "Instala: pip install google-api-python-client google-auth-oauthlib"
            )

    def publish_video(
        self,
        video_path: Path,
        caption: str,
        hashtags: list[str],
        thumbnail_path: Optional[Path] = None,
    ) -> str:
        from googleapiclient.http import MediaFileUpload

        svc = self._get_service()
        tags = [t.lstrip("#") for t in hashtags]
        description = self.format_caption(caption, hashtags, max_length=5000)

        body = {
            "snippet": {
                "title": caption[:100],
                "description": description,
                "tags": tags[:500],
                "categoryId": "22",   # People & Blogs
                "defaultLanguage": "es",
            },
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
        }

        log.info("Subiendo video a YouTube: %s", video_path.name)
        media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
        request = svc.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                log.debug("Progreso upload YouTube: %d%%", int(status.progress() * 100))

        video_id = response["id"]
        log.info("Short de YouTube publicado: %s", video_id)

        if thumbnail_path and thumbnail_path.exists():
            self._set_thumbnail(svc, video_id, thumbnail_path)

        return video_id

    def _set_thumbnail(self, svc, video_id: str, thumbnail_path: Path):
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg")
        svc.thumbnails().set(videoId=video_id, media_body=media).execute()
        log.info("Thumbnail configurada para %s", video_id)

    def get_post_metrics(self, post_id: str) -> dict:
        svc = self._get_service()
        resp = svc.videos().list(
            part="statistics",
            id=post_id,
        ).execute()
        items = resp.get("items", [])
        if not items:
            return {}
        stats = items[0].get("statistics", {})
        return {
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
        }

    def get_comments(self, post_id: str, limit: int = 50) -> list[dict]:
        svc = self._get_service()
        resp = svc.commentThreads().list(
            part="snippet",
            videoId=post_id,
            maxResults=limit,
            order="time",
        ).execute()
        comments = []
        for item in resp.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "id": item["id"],
                "text": top["textDisplay"],
                "author": top["authorDisplayName"],
                "likes": top["likeCount"],
                "timestamp": top["publishedAt"],
            })
        return comments

    def reply_comment(self, post_id: str, comment_id: str, text: str) -> bool:
        svc = self._get_service()
        try:
            svc.comments().insert(
                part="snippet",
                body={
                    "snippet": {
                        "parentId": comment_id,
                        "textOriginal": text,
                    }
                },
            ).execute()
            log.info("Respuesta publicada en YouTube comentario %s", comment_id)
            return True
        except Exception as e:
            log.error("Error respondiendo en YouTube: %s", e)
            return False
