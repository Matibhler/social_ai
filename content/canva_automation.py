"""
Automatización de Canva vía Playwright.
Permite crear proyectos, insertar recursos y exportar videos desde Canva.
NOTA: Requiere cuenta Canva activa y sesión iniciada.
"""

import asyncio
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser

from core.logger import get_logger

log = get_logger(__name__)

CANVA_URL = "https://www.canva.com"


class CanvaAutomation:
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None

    async def __aenter__(self):
        self._pw = await async_playwright().start()
        # Persistent context para mantener la sesión de Canva
        self.ctx = await self._pw.chromium.launch_persistent_context(
            user_data_dir=str(Path.home() / ".social_ai" / "canva_profile"),
            headless=False,   # Canva requiere navegador visible
            viewport={"width": 1920, "height": 1080},
            args=["--start-maximized"],
        )
        self.page = await self.ctx.new_page()
        return self

    async def __aexit__(self, *args):
        await self.ctx.close()
        await self._pw.stop()

    async def ensure_logged_in(self) -> bool:
        """Verifica que el usuario esté logueado en Canva."""
        await self.page.goto(CANVA_URL, wait_until="networkidle")
        await asyncio.sleep(2)
        if "canva.com/design" in self.page.url or await self.page.query_selector("[data-testid='home-page']"):
            log.info("Sesión de Canva activa")
            return True
        log.warning("No hay sesión activa. Por favor inicia sesión en el navegador.")
        # Esperar hasta 2 minutos a que el usuario inicie sesión
        for _ in range(24):
            await asyncio.sleep(5)
            if "designs" in self.page.url or "dashboard" in self.page.url:
                return True
        return False

    async def create_project(self, template_keyword: str = "reel vertical") -> str:
        """Crea un nuevo proyecto en Canva y retorna la URL del diseño."""
        log.info("Creando proyecto Canva: '%s'", template_keyword)
        await self.page.goto(f"{CANVA_URL}/create", wait_until="networkidle")
        await asyncio.sleep(2)

        # Buscar template de video vertical
        search = await self.page.wait_for_selector("input[placeholder*='Search']", timeout=10000)
        await search.fill(template_keyword)
        await search.press("Enter")
        await asyncio.sleep(3)

        # Clic en primer resultado
        first_template = await self.page.wait_for_selector(
            "[data-testid='template-item']:first-child", timeout=10000
        )
        await first_template.click()
        await asyncio.sleep(2)

        # Botón de "Usar esta plantilla" o similar
        try:
            btn = await self.page.wait_for_selector(
                "button:has-text('Usar'), button:has-text('Use')", timeout=5000
            )
            await btn.click()
        except Exception:
            pass

        await self.page.wait_for_url("**/design/**", timeout=20000)
        design_url = self.page.url
        log.info("Proyecto creado: %s", design_url)
        return design_url

    async def upload_media(self, file_path: Path) -> bool:
        """Sube un archivo multimedia a Canva."""
        log.info("Subiendo media: %s", file_path.name)
        try:
            # Hacer clic en el panel de Uploads
            uploads_btn = await self.page.wait_for_selector(
                "[aria-label='Uploads'], [data-testid='uploads-panel']", timeout=8000
            )
            await uploads_btn.click()
            await asyncio.sleep(1)

            # Botón de subir archivo
            upload_btn = await self.page.wait_for_selector(
                "button:has-text('Upload'), input[type='file']", timeout=5000
            )
            if await upload_btn.get_attribute("type") == "file":
                await upload_btn.set_input_files(str(file_path))
            else:
                async with self.page.expect_file_chooser() as fc_info:
                    await upload_btn.click()
                file_chooser = await fc_info.value
                await file_chooser.set_files(str(file_path))

            await asyncio.sleep(5)  # esperar upload
            log.info("Media subida exitosamente")
            return True
        except Exception as e:
            log.error("Error subiendo media: %s", e)
            return False

    async def insert_text(self, text: str, font_size: int = 72, color: str = "#FFFFFF") -> bool:
        """Inserta un cuadro de texto en el diseño."""
        try:
            text_btn = await self.page.wait_for_selector(
                "[aria-label='Text'], [data-testid='text-panel']", timeout=8000
            )
            await text_btn.click()
            await asyncio.sleep(1)

            heading_btn = await self.page.wait_for_selector(
                "button:has-text('Add a heading')", timeout=5000
            )
            await heading_btn.click()
            await asyncio.sleep(1)

            # Escribir el texto
            active = await self.page.wait_for_selector(".canva-text-editor", timeout=5000)
            await active.triple_click()
            await active.type(text)
            log.info("Texto insertado: '%s'", text[:50])
            return True
        except Exception as e:
            log.error("Error insertando texto: %s", e)
            return False

    async def export_video(self, output_path: Path, format: str = "MP4") -> Optional[Path]:
        """Exporta el diseño como video."""
        log.info("Exportando video de Canva…")
        try:
            # Botón compartir/exportar
            share_btn = await self.page.wait_for_selector(
                "button:has-text('Share'), button:has-text('Compartir')", timeout=10000
            )
            await share_btn.click()
            await asyncio.sleep(2)

            # Descargar
            download_btn = await self.page.wait_for_selector(
                "button:has-text('Download'), button:has-text('Descargar')", timeout=8000
            )
            await download_btn.click()
            await asyncio.sleep(2)

            # Seleccionar formato MP4
            if format == "MP4":
                try:
                    format_sel = await self.page.wait_for_selector(
                        "select, [data-testid='file-type-selector']", timeout=5000
                    )
                    await format_sel.select_option(label="MP4 Video")
                except Exception:
                    pass

            # Iniciar descarga
            async with self.page.expect_download(timeout=120000) as dl_info:
                confirm_btn = await self.page.wait_for_selector(
                    "button:has-text('Download'), button:has-text('Descargar')",
                    timeout=10000,
                )
                await confirm_btn.click()

            download = await dl_info.value
            await download.save_as(str(output_path))
            log.info("Video exportado: %s", output_path)
            return output_path

        except Exception as e:
            log.error("Error exportando de Canva: %s", e)
            return None

    async def full_canva_pipeline(
        self,
        media_files: list[Path],
        title_text: str,
        hook_text: str,
        output_path: Path,
    ) -> Optional[Path]:
        """Pipeline completo: crear → subir media → texto → exportar."""
        if not await self.ensure_logged_in():
            raise RuntimeError("No se pudo iniciar sesión en Canva")

        await self.create_project("video vertical reel")

        for f in media_files:
            await self.upload_media(f)
            await asyncio.sleep(2)

        await self.insert_text(title_text)
        await asyncio.sleep(1)
        await self.insert_text(hook_text)

        return await self.export_video(output_path)
