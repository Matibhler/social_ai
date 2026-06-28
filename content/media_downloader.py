"""
Descarga de material multimedia desde APIs gratuitas (Pexels, Pixabay).
Todos los medios tienen licencia libre de derechos para uso comercial.
"""

import hashlib
import mimetypes
from pathlib import Path
from typing import Optional

import httpx

from core.config import settings
from core.database import get_session
from core.logger import get_logger
from core.models import MediaAsset

log = get_logger(__name__)

HEADERS_PEXELS = {"Authorization": settings.PEXELS_API_KEY}
PIXABAY_KEY = settings.PIXABAY_API_KEY


class MediaDownloader:

    def __init__(self):
        self.client = httpx.Client(timeout=60, follow_redirects=True)
        settings.MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    def __del__(self):
        self.client.close()

    # ── Pexels ────────────────────────────────────────────────────────────

    def search_pexels_videos(self, query: str, per_page: int = 5) -> list[dict]:
        if not settings.PEXELS_API_KEY:
            log.warning("PEXELS_API_KEY no configurada")
            return []

        resp = self.client.get(
            "https://api.pexels.com/videos/search",
            headers=HEADERS_PEXELS,
            params={"query": query, "per_page": per_page, "orientation": "portrait"},
        )
        if resp.status_code != 200:
            log.error("Pexels error: %s", resp.text)
            return []

        results = []
        for v in resp.json().get("videos", []):
            # Preferir HD vertical
            best = next(
                (
                    f for f in sorted(v["video_files"], key=lambda x: x.get("height", 0), reverse=True)
                    if f.get("width", 9999) < f.get("height", 0)  # portrait
                ),
                v["video_files"][0] if v["video_files"] else None,
            )
            if best:
                results.append({
                    "source": "pexels",
                    "source_id": str(v["id"]),
                    "url": best["link"],
                    "asset_type": "video",
                    "width": best.get("width"),
                    "height": best.get("height"),
                    "duration": v.get("duration"),
                    "license": "Pexels License (free commercial use)",
                })
        return results

    def search_pexels_images(self, query: str, per_page: int = 5) -> list[dict]:
        if not settings.PEXELS_API_KEY:
            return []

        resp = self.client.get(
            "https://api.pexels.com/v1/search",
            headers=HEADERS_PEXELS,
            params={"query": query, "per_page": per_page, "orientation": "portrait"},
        )
        if resp.status_code != 200:
            return []

        return [
            {
                "source": "pexels",
                "source_id": str(p["id"]),
                "url": p["src"]["large2x"],
                "asset_type": "image",
                "width": p["width"],
                "height": p["height"],
                "license": "Pexels License (free commercial use)",
            }
            for p in resp.json().get("photos", [])
        ]

    # ── Pixabay ───────────────────────────────────────────────────────────

    def search_pixabay_videos(self, query: str, per_page: int = 5) -> list[dict]:
        if not PIXABAY_KEY:
            return []

        resp = self.client.get(
            "https://pixabay.com/api/videos/",
            params={
                "key": PIXABAY_KEY,
                "q": query,
                "per_page": per_page,
                "video_type": "film",
            },
        )
        if resp.status_code != 200:
            return []

        results = []
        for v in resp.json().get("hits", []):
            videos = v.get("videos", {})
            src = (
                videos.get("large") or videos.get("medium") or videos.get("small") or {}
            )
            if src.get("url"):
                results.append({
                    "source": "pixabay",
                    "source_id": str(v["id"]),
                    "url": src["url"],
                    "asset_type": "video",
                    "width": src.get("width"),
                    "height": src.get("height"),
                    "duration": v.get("duration"),
                    "license": "Pixabay License (free commercial use)",
                })
        return results

    # ── Descarga ──────────────────────────────────────────────────────────

    def download(self, media_info: dict, content_id: int | None = None) -> Optional[Path]:
        url = media_info["url"]
        ext = _url_to_ext(url, media_info.get("asset_type", "video"))
        filename = hashlib.md5(url.encode()).hexdigest()[:16] + ext
        dest = settings.MEDIA_DIR / filename

        if dest.exists():
            log.debug("Ya existe en caché: %s", dest)
        else:
            log.info("Descargando: %s", url[:80])
            try:
                with self.client.stream("GET", url) as r:
                    r.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in r.iter_bytes(chunk_size=65536):
                            f.write(chunk)
                log.info("Descargado: %s (%.1f MB)", dest.name, dest.stat().st_size / 1_048_576)
            except Exception as e:
                log.error("Error descargando %s: %s", url, e)
                return None

        if content_id:
            self._save_asset(media_info, dest, content_id)

        return dest

    def search_youtube_videos(self, query: str, max_results: int = 3, used_ids: set = None) -> list[dict]:
        try:
            import yt_dlp
        except ImportError:
            log.warning("yt-dlp no instalado")
            return []

        used_ids = used_ids or set()
        results = []
        ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch{max_results * 3}:{query}", download=False)
                for entry in (info.get("entries") or []):
                    if not entry:
                        continue
                    vid_id = entry.get("id", "")
                    if not vid_id or vid_id in used_ids:
                        continue
                    results.append({
                        "source": "youtube",
                        "source_id": vid_id,
                        "url": f"https://www.youtube.com/watch?v={vid_id}",
                        "asset_type": "video",
                        "duration": entry.get("duration"),
                        "license": "youtube",
                    })
                    if len(results) >= max_results:
                        break
        except Exception as e:
            log.error("YouTube search error: %s", e)
        return results

    def download_youtube_clip(self, video_info: dict, content_id: int = None) -> "Optional[Path]":
        try:
            import yt_dlp
        except ImportError:
            return None

        vid_id = video_info["source_id"]
        dest = settings.MEDIA_DIR / f"yt_{vid_id}.mp4"
        if dest.exists():
            log.debug("YouTube clip ya en caché: %s", dest)
            if content_id:
                self._save_asset(video_info, dest, content_id)
            return dest

        log.info("Descargando clip YouTube: %s", video_info["url"])
        outtmpl = str(settings.MEDIA_DIR / f"yt_{vid_id}.%(ext)s")
        ydl_opts = {
            "format": "bestvideo[height<=720][ext=mp4]/bestvideo[height<=720]/best[height<=720]",
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
        }
        try:
            from yt_dlp.utils import download_range_func
            ydl_opts["download_ranges"] = download_range_func(None, [(0, 30)])
            ydl_opts["force_keyframes_at_cuts"] = True
        except ImportError:
            pass

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_info["url"]])
            # find downloaded file (yt-dlp picks the extension)
            for ext in (".mp4", ".webm", ".mkv", ".mov"):
                candidate = settings.MEDIA_DIR / f"yt_{vid_id}{ext}"
                if candidate.exists():
                    if ext != ".mp4":
                        candidate.rename(dest)
                    if content_id:
                        self._save_asset(video_info, dest, content_id)
                    return dest
        except Exception as e:
            log.error("YouTube download error: %s", e)
        return None

    def _get_used_source_ids(self) -> set:
        try:
            with get_session() as db:
                from sqlalchemy import select as _select
                rows = db.execute(_select(MediaAsset.source_id)).scalars().all()
                return set(rows)
        except Exception:
            return set()

    def download_batch(
        self, queries: list[str], content_id: int, max_per_query: int = 2
    ) -> list[Path]:
        used_ids = self._get_used_source_ids()
        paths = []
        for query in queries:
            # Try Pexels first, filter already-used clips
            results = [r for r in self.search_pexels_videos(query, per_page=max_per_query + 3)
                       if r["source_id"] not in used_ids]
            # Fall back to Pixabay
            if not results:
                results = [r for r in self.search_pixabay_videos(query, per_page=max_per_query + 3)
                           if r["source_id"] not in used_ids]
            # Fall back to YouTube
            if not results:
                results = self.search_youtube_videos(query, max_results=max_per_query, used_ids=used_ids)

            for item in results[:max_per_query]:
                if item["source"] == "youtube":
                    p = self.download_youtube_clip(item, content_id=content_id)
                else:
                    p = self.download(item, content_id=content_id)
                if p:
                    paths.append(p)
                    used_ids.add(item["source_id"])
        return paths

    def _save_asset(self, info: dict, local_path: Path, content_id: int):
        with get_session() as db:
            asset = MediaAsset(
                content_id=content_id,
                source=info.get("source", "unknown"),
                source_id=info.get("source_id", ""),
                url=info.get("url", ""),
                local_path=str(local_path),
                asset_type=info.get("asset_type", "video"),
                duration=info.get("duration"),
                width=info.get("width"),
                height=info.get("height"),
                license=info.get("license", ""),
            )
            db.add(asset)


def _url_to_ext(url: str, asset_type: str) -> str:
    for ext in [".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".webp"]:
        if ext in url.lower():
            return ext
    return ".mp4" if asset_type == "video" else ".jpg"
