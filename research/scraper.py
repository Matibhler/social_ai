"""
Módulo de scraping de cuentas competidoras.
Usa Playwright en modo headless para extraer datos de publicaciones.
"""

import asyncio
import re
from datetime import datetime
from typing import Optional

from playwright.async_api import async_playwright, Browser, Page

from core.config import settings
from core.database import get_session
from core.logger import get_logger
from core.models import CompetitorAccount, CompetitorPost, Platform

log = get_logger(__name__)


class SocialScraper:
    def __init__(self):
        self.browser: Optional[Browser] = None

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        return self

    async def __aexit__(self, *args):
        if self.browser:
            await self.browser.close()
        await self._playwright.stop()

    async def _new_page(self) -> Page:
        ctx = await self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        return await ctx.new_page()

    # ── Instagram ─────────────────────────────────────────────────────────

    async def scrape_instagram_profile(
        self, username: str, max_posts: int = 20
    ) -> list[dict]:
        """Extrae posts recientes de un perfil de Instagram."""
        log.info("Scraping Instagram: @%s", username)
        page = await self._new_page()
        posts_data = []

        try:
            await page.goto(
                f"https://www.instagram.com/{username}/",
                wait_until="networkidle",
                timeout=30_000,
            )
            await page.wait_for_timeout(2000)

            # Aceptar cookies si aparece
            try:
                await page.click("text=Allow all cookies", timeout=3000)
            except Exception:
                pass

            # Extraer links de posts
            post_links = await page.eval_on_selector_all(
                "article a[href*='/p/'], article a[href*='/reel/']",
                "els => els.map(e => e.href)",
            )
            post_links = list(dict.fromkeys(post_links))[:max_posts]

            # Extraer seguidores del perfil
            followers = 0
            try:
                followers_text = await page.inner_text(
                    "a[href$='/followers/'] span", timeout=3000
                )
                followers = _parse_number(followers_text)
            except Exception:
                pass

            for url in post_links:
                try:
                    data = await self._scrape_instagram_post(page, url)
                    if data:
                        posts_data.append(data)
                    await asyncio.sleep(1.5)  # respetar rate limits
                except Exception as e:
                    log.warning("Error scraping post %s: %s", url, e)

            log.info("Scraped %d posts de @%s", len(posts_data), username)
            return posts_data, followers

        finally:
            await page.close()

    async def _scrape_instagram_post(self, page: Page, url: str) -> Optional[dict]:
        await page.goto(url, wait_until="networkidle", timeout=20_000)
        await page.wait_for_timeout(1500)

        try:
            caption = await page.inner_text("h1", timeout=5000)
        except Exception:
            caption = ""

        try:
            likes_text = await page.inner_text(
                "section span[class*='x193iq5w']", timeout=3000
            )
            likes = _parse_number(likes_text)
        except Exception:
            likes = 0

        is_reel = "/reel/" in url
        hook = caption[:100] if caption else ""
        hashtags = re.findall(r"#(\w+)", caption)
        cta = _extract_cta(caption)

        return {
            "url": url,
            "platform": Platform.INSTAGRAM,
            "post_id": url.split("/p/")[-1].split("/reel/")[-1].strip("/"),
            "caption": caption,
            "likes": likes,
            "hook_text": hook,
            "cta_text": cta,
            "hashtags": hashtags,
            "content_format": "reel" if is_reel else "post",
            "scraped_at": datetime.utcnow(),
        }

    # ── TikTok ────────────────────────────────────────────────────────────

    async def scrape_tiktok_profile(
        self, username: str, max_posts: int = 20
    ) -> tuple[list[dict], int]:
        log.info("Scraping TikTok: @%s", username)
        page = await self._new_page()
        posts_data = []

        try:
            await page.goto(
                f"https://www.tiktok.com/@{username}",
                wait_until="networkidle",
                timeout=30_000,
            )
            await page.wait_for_timeout(3000)

            followers = 0
            try:
                followers_text = await page.inner_text(
                    "[data-e2e='followers-count']", timeout=5000
                )
                followers = _parse_number(followers_text)
            except Exception:
                pass

            # Scroll para cargar más posts
            for _ in range(3):
                await page.keyboard.press("End")
                await page.wait_for_timeout(1500)

            post_links = await page.eval_on_selector_all(
                "a[href*='/video/']",
                "els => [...new Set(els.map(e => e.href))]",
            )
            post_links = post_links[:max_posts]

            for url in post_links:
                try:
                    data = await self._scrape_tiktok_video(page, url)
                    if data:
                        posts_data.append(data)
                    await asyncio.sleep(2)
                except Exception as e:
                    log.warning("Error scraping TikTok %s: %s", url, e)

            return posts_data, followers
        finally:
            await page.close()

    async def _scrape_tiktok_video(self, page: Page, url: str) -> Optional[dict]:
        await page.goto(url, wait_until="networkidle", timeout=20_000)
        await page.wait_for_timeout(2000)

        try:
            caption = await page.inner_text(
                "[data-e2e='browse-video-desc']", timeout=5000
            )
        except Exception:
            caption = ""

        try:
            views_text = await page.inner_text(
                "[data-e2e='browse-video-play-count']", timeout=3000
            )
            views = _parse_number(views_text)
        except Exception:
            views = 0

        try:
            likes_text = await page.inner_text(
                "[data-e2e='browse-like-count']", timeout=3000
            )
            likes = _parse_number(likes_text)
        except Exception:
            likes = 0

        hashtags = re.findall(r"#(\w+)", caption)

        return {
            "url": url,
            "platform": Platform.TIKTOK,
            "post_id": url.split("/video/")[-1].strip("/"),
            "caption": caption,
            "views": views,
            "likes": likes,
            "hook_text": caption[:100],
            "cta_text": _extract_cta(caption),
            "hashtags": hashtags,
            "content_format": "video",
            "scraped_at": datetime.utcnow(),
        }


# ── Funciones auxiliares ──────────────────────────────────────────────────────

def _parse_number(text: str) -> int:
    """Convierte '1.2M', '45K', '1,234' → int."""
    text = text.strip().replace(",", "").replace(".", "")
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    for suffix, mult in multipliers.items():
        if text.upper().endswith(suffix):
            try:
                return int(float(text[:-1]) * mult)
            except ValueError:
                return 0
    try:
        return int(text)
    except ValueError:
        return 0


def _extract_cta(text: str) -> str:
    """Detecta llamados a la acción comunes."""
    patterns = [
        r"(sigue|sígueme|follow|link en bio|enlace en bio|comenta|comparte|"
        r"guarda|save|comenta abajo|deja tu|cuéntame|etiqueta)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            start = max(0, m.start() - 10)
            end = min(len(text), m.end() + 60)
            return text[start:end].strip()
    return ""


# ── Guardado en DB ────────────────────────────────────────────────────────────

def save_scrape_results(
    username: str,
    platform: Platform,
    posts: list[dict],
    followers: int,
    niche: str,
) -> CompetitorAccount:
    with get_session() as db:
        account = (
            db.query(CompetitorAccount)
            .filter_by(username=username, platform=platform)
            .first()
        )
        if not account:
            account = CompetitorAccount(
                username=username,
                platform=platform,
                niche=niche,
            )
            db.add(account)
            db.flush()

        account.followers = followers
        account.last_analyzed = datetime.utcnow()

        for p in posts:
            existing = (
                db.query(CompetitorPost)
                .filter_by(post_id=p["post_id"])
                .first()
            )
            if not existing:
                post = CompetitorPost(account_id=account.id, **p)
                db.add(post)

        db.commit()
        log.info("Guardados %d posts de @%s en DB", len(posts), username)
        return account
