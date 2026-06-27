"""
Motor TTS (Text-to-Speech) con soporte para edge-tts y Coqui TTS.
edge-tts: sin costo, voces de Microsoft de alta calidad.
"""

import asyncio
from pathlib import Path

from core.config import settings
from core.logger import get_logger

log = get_logger(__name__)


class TTSEngine:
    def __init__(self, engine: str = None, voice: str = None):
        self.engine = engine or settings.TTS_ENGINE
        self.voice = voice or settings.TTS_VOICE

    def synthesize(self, text: str, output_path: Path) -> Path:
        """Sintetiza texto a audio. Retorna la ruta del archivo."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if self.engine == "edge-tts":
            return self._edge_tts(text, output_path)
        elif self.engine == "coqui":
            return self._coqui_tts(text, output_path)
        else:
            raise ValueError(f"Motor TTS no soportado: {self.engine}")

    def _edge_tts(self, text: str, output_path: Path) -> Path:
        try:
            import edge_tts
        except ImportError:
            raise ImportError("Instala edge-tts: pip install edge-tts")

        mp3_path = output_path.with_suffix(".mp3")

        async def _run():
            communicate = edge_tts.Communicate(text, self.voice)
            await communicate.save(str(mp3_path))

        asyncio.run(_run())
        log.info("Audio TTS generado: %s", mp3_path)
        return mp3_path

    def _coqui_tts(self, text: str, output_path: Path) -> Path:
        try:
            from TTS.api import TTS
        except ImportError:
            raise ImportError("Instala Coqui TTS: pip install TTS")

        wav_path = output_path.with_suffix(".wav")
        tts = TTS(model_name="tts_models/es/css10/vits", progress_bar=False, gpu=False)
        tts.tts_to_file(text=text, file_path=str(wav_path))
        log.info("Audio Coqui TTS generado: %s", wav_path)
        return wav_path

    def get_available_voices(self) -> list[str]:
        """Lista voces disponibles (solo edge-tts)."""
        if self.engine != "edge-tts":
            return []

        async def _list():
            import edge_tts
            voices = await edge_tts.list_voices()
            return [v["ShortName"] for v in voices if v["Locale"].startswith("es")]

        return asyncio.run(_list())


tts = TTSEngine()
