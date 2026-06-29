"""
Editor de video usando FFmpeg.
Produce videos verticales 1080x1920 optimizados para Reels/Shorts/TikTok.
"""

import subprocess
from pathlib import Path
from typing import Optional

from core.config import settings
from core.logger import get_logger

log = get_logger(__name__)

W = settings.VIDEO_WIDTH    # 1080
H = settings.VIDEO_HEIGHT   # 1920
FPS = settings.VIDEO_FPS    # 30


def run_ffmpeg(*args: str, check: bool = True, cwd: str = None) -> subprocess.CompletedProcess:
    args = list(args)
    # Insert -pix_fmt yuv420p just before the output filename (last arg) so FFmpeg
    # treats it as an output option — placing it before -i would make it an input option
    if "libx264" in args and "-pix_fmt" not in args:
        args = args[:-1] + ["-pix_fmt", "yuv420p"] + [args[-1]]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", *args]
    log.debug("FFmpeg: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if check and result.returncode != 0:
        log.error("FFmpeg stderr: %s", result.stderr)
        raise RuntimeError(f"FFmpeg falló (código {result.returncode})")
    return result


class VideoEditor:

    # Layout constants for the 1080x1920 Reels frame
    # Top black band: 0–520px   → paragraph text lives here
    # Clip zone:    520–1820px  → 1300px tall, full width
    # Bottom black band: 1820–1920px
    CLIP_Y = 520
    CLIP_H = 1300

    def prepare_clip(self, video_path: Path, duration: float, output: Path) -> Path:
        """Scale clip to fit the middle band of the 1080x1920 Reels layout."""
        run_ffmpeg(
            "-i", str(video_path),
            "-t", str(duration),
            "-vf", (
                # 1. Fit clip inside 1080×940 (letterbox if landscape, crop if portrait)
                f"scale={W}:{self.CLIP_H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{self.CLIP_H},"
                # 2. Pad to full 1080×1920 with black — clip sits at y=520
                f"pad={W}:{H}:0:{self.CLIP_Y}:black,"
                f"fps={FPS}"
            ),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-an",
            str(output),
        )
        return output

    def concat_clips(self, clips: list[Path], output: Path) -> Path:
        """Concatena clips usando el método de lista de archivos."""
        list_file = output.parent / "concat_list.txt"
        list_file.write_text(
            "\n".join(f"file '{c.resolve()}'" for c in clips),
            encoding="utf-8",
        )
        run_ffmpeg(
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            str(output),
        )
        list_file.unlink(missing_ok=True)
        return output

    def add_audio(
        self,
        video_path: Path,
        audio_path: Path,
        output: Path,
        loop_video: bool = True,
    ) -> Path:
        """Combina video y audio; el video se repite si es más corto que el audio."""
        loop_flag = ["-stream_loop", "-1"] if loop_video else []
        run_ffmpeg(
            *loop_flag, "-i", str(video_path),
            "-i", str(audio_path),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            str(output),
        )
        return output

    def burn_subtitles(
        self, video_path: Path, subtitle_path: Path, output: Path
    ) -> Path:
        """Quema subtítulos .srt o .ass en el video."""
        # Use just the filename (no path) to avoid Windows drive-letter colon issues in FFmpeg filters
        ext = subtitle_path.suffix.lower()
        sub_name = subtitle_path.name
        if ext == ".ass":
            sub_filter = f"ass={sub_name}"
        else:
            sub_filter = f"subtitles={sub_name}"

        run_ffmpeg(
            "-i", str(video_path),
            "-vf", sub_filter,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            str(output),
            cwd=str(subtitle_path.parent),
        )
        return output

    def add_text_overlay(
        self,
        video_path: Path,
        text: str,
        output: Path,
        y_pos: str = "h-th-100",
        font_size: int = 60,
        color: str = "white",
    ) -> Path:
        """Añade texto superpuesto (título/CTA) al video."""
        safe_text = text.replace("'", "\\'").replace(":", "\\:")
        run_ffmpeg(
            "-i", str(video_path),
            "-vf", (
                f"drawtext=text='{safe_text}'"
                f":fontsize={font_size}:fontcolor={color}"
                f":x=(w-text_w)/2:y={y_pos}"
                f":shadowcolor=black:shadowx=2:shadowy=2"
                f":box=1:boxcolor=black@0.4:boxborderw=10"
            ),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            str(output),
        )
        return output

    def add_background_music(
        self,
        video_path: Path,
        music_path: Path,
        output: Path,
        music_volume: float = 0.35,
    ) -> Path:
        """Mezcla música de fondo con el audio de voz en off."""
        run_ffmpeg(
            "-i", str(video_path),
            "-i", str(music_path),
            "-filter_complex",
            f"[1:a]volume={music_volume},aloop=loop=-1:size=2e+09[bg];"
            "[0:a][bg]amix=inputs=2:duration=first[outa]",
            "-map", "0:v", "-map", "[outa]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            str(output),
        )
        return output

    def extract_thumbnail(self, video_path: Path, output: Path, time: float = 1.0) -> Path:
        """Extrae frame para miniatura."""
        run_ffmpeg(
            "-ss", str(time),
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(output),
        )
        return output

    def full_pipeline(
        self,
        clips: list[Path],
        audio_path: Path,
        subtitle_path: Optional[Path],
        hook_text: str,
        output_path: Path,
        music_path: Optional[Path] = None,
    ) -> Path:
        """
        Pipeline completo:
        clips → concat → add_audio → subtítulos → texto hook → música → export
        """
        tmp = output_path.parent / "tmp"
        tmp.mkdir(exist_ok=True)

        import subprocess as _sp

        log.info("Iniciando pipeline de video: %s", output_path.name)

        def _get_duration(path: Path) -> float:
            r = _sp.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True,
            )
            try:
                return float(r.stdout.strip())
            except (ValueError, AttributeError):
                return 3.0

        # 1. Preparar clips cinématicos (5 segundos cada uno — 2-3 clips = 10-15s total)
        prepared = []
        for i, clip in enumerate(clips):
            out = tmp / f"clip_{i:03d}.mp4"
            self.prepare_clip(clip, duration=5, output=out)
            prepared.append(out)

        # 2. Concatenar clips (simple concat — fast cuts are already dynamic)
        concat_out = tmp / "concat.mp4"
        if len(prepared) > 1:
            self.concat_clips(prepared, concat_out)
        else:
            import shutil as _shutil
            _shutil.copy2(str(prepared[0]), str(concat_out))

        # 2. Agregar audio (voz en off)
        with_audio = tmp / "with_audio.mp4"
        self.add_audio(concat_out, audio_path, with_audio)

        # 3. Subtítulos
        if subtitle_path and subtitle_path.exists():
            with_subs = tmp / "with_subs.mp4"
            self.burn_subtitles(with_audio, subtitle_path, with_subs)
        else:
            with_subs = with_audio

        # 4. Música de fondo (opcional)
        if music_path and music_path.exists():
            final_tmp = tmp / "with_music.mp4"
            self.add_background_music(with_subs, music_path, final_tmp)
        else:
            final_tmp = with_subs

        # 6. Mover a destino final
        import shutil
        shutil.move(str(final_tmp), str(output_path))
        log.info("Video final: %s", output_path)

        # Limpiar temporales (ignore locked files on Windows)
        for f in tmp.glob("*.mp4"):
            try:
                f.unlink()
            except Exception:
                pass

        return output_path


    def add_music_only(
        self,
        video_path: Path,
        music_path: Path,
        output: Path,
        volume: float = 0.75,
    ) -> Path:
        """Attach music as the sole audio track (no voice). Loops music to fill video."""
        run_ffmpeg(
            "-i", str(video_path),
            "-stream_loop", "-1", "-i", str(music_path),
            "-filter_complex",
            f"[1:a]volume={volume}[bg]",
            "-map", "0:v", "-map", "[bg]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(output),
        )
        return output

    @staticmethod
    def _ensure_montserrat() -> tuple[str, str]:
        """Download Montserrat-Bold.ttf to data/fonts/ if absent. Returns (dir, filename)."""
        import httpx as _httpx
        fonts_dir = settings.DATA_DIR / "fonts"
        fonts_dir.mkdir(exist_ok=True)
        font_path = fonts_dir / "Montserrat-Bold.ttf"
        if not font_path.exists():
            # Try multiple sources — Google Fonts repo moved to variable fonts
            url = (
                "https://cdn.jsdelivr.net/fontsource/fonts/montserrat@latest"
                "/latin-700-normal.ttf"
            )
            try:
                log.info("Descargando Montserrat Bold...")
                r = _httpx.get(url, follow_redirects=True, timeout=30)
                r.raise_for_status()
                font_path.write_bytes(r.content)
                log.info("Fuente guardada: %s", font_path)
            except Exception as e:
                log.warning("No se pudo descargar Montserrat: %s — usando fuente por defecto", e)
                return "", ""
        return str(fonts_dir), "Montserrat-Bold.ttf"

    def add_paragraph_overlay(
        self,
        video_path: Path,
        text: str,
        output: Path,
    ) -> Path:
        """Burn complete paragraph (top band) + timed CTA (bottom band) on 1080x1920 Reels."""
        fonts_dir, font_file = self._ensure_montserrat()
        # fontfile uses just the filename — cwd is set to fonts_dir so no Windows path issues
        font_opt = f":fontfile='{font_file}'" if font_file else ""

        import re as _re
        # Strip chars that break FFmpeg filter string parsing
        clean = (
            text.replace("'", "").replace('"', "").replace("\\", " ")
                .replace(":", " ").replace(",", " ")
                .replace("[", "").replace("]", "").replace("@", "")
        ).strip()

        # Extract complete sentences — never start or end mid-sentence
        sentences = _re.findall(r'[^.!?]+[.!?]', clean)
        if not sentences:
            sentences = [clean]

        def _wrap(txt, max_chars):
            wds = txt.split()
            ls, cur = [], []
            for w in wds:
                if len(" ".join(cur + [w])) > max_chars and cur:
                    ls.append(" ".join(cur))
                    cur = [w]
                else:
                    cur.append(w)
            if cur:
                ls.append(" ".join(cur))
            return ls

        # Auto-size: fit as many complete sentences as possible in the band
        # Band available: CLIP_Y - 60px margins = 460px
        BAND = self.CLIP_Y - 60   # 460px
        font_size = 40
        line_h = font_size + 12   # 52px
        max_lines = BAND // line_h  # 8 lines at 40px

        lines = []
        for sent in sentences:
            sent_lines = _wrap(sent.strip(), max_chars=36)
            if len(lines) + len(sent_lines) <= max_lines:
                lines.extend(sent_lines)
            else:
                break  # stop before cutting a sentence in half

        # If even the first sentence alone exceeds max_lines, scale font down
        if not lines:
            for fsize in (36, 32, 28):
                lh = fsize + 10
                ml = BAND // lh
                lines = _wrap(sentences[0].strip(), max_chars=38)[:ml]
                font_size, line_h = fsize, lh
                break

        if not lines:
            lines = [""]

        n = len(lines)
        block_h = n * line_h - (line_h - font_size)
        band_center = self.CLIP_Y // 2   # 260px
        start_y = max(20, band_center - block_h // 2)

        vf_parts = []
        for i, line in enumerate(lines):
            y = start_y + i * line_h
            vf_parts.append(
                f"drawtext=text='{line}'{font_opt}"
                f":fontsize={font_size}:fontcolor=white"
                f":x=(w-text_w)/2:y={y}"
                f":shadowcolor=black@0.85:shadowx=2:shadowy=2"
            )

        # "Read the description" — bottom of clip zone, fades in red at 3.5 s, no background strip
        cta_y = self.CLIP_Y + self.CLIP_H - 90       # last 90px of clip zone
        vf_parts.append(
            f"drawtext=text='Read the description'{font_opt}"
            f":fontsize=34:fontcolor=red"
            f":x=(w-text_w)/2:y={cta_y}"
            f":alpha='if(gte(t,3.5),min((t-3.5)/0.6,1),0)'"
            f":shadowcolor=black@0.9:shadowx=3:shadowy=3"
        )

        run_ffmpeg(
            "-i", str(video_path),
            "-vf", ",".join(vf_parts),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            str(output),
            cwd=fonts_dir if fonts_dir else None,
        )
        return output

    def silent_pipeline(
        self,
        clips: list[Path],
        hook_text: str,
        output_path: Path,
        music_path: Optional[Path] = None,
    ) -> Path:
        """
        Silent cinematic pipeline: clips → concat → emotional paragraph → music.
        No voice, no subtitles. Music is the only audio.
        """
        import shutil as _shutil
        tmp = output_path.parent / "tmp"
        tmp.mkdir(exist_ok=True)

        log.info("Pipeline silencioso: %d clips → %s", len(clips), output_path.name)

        # 1. Prepare clips (5s each)
        prepared = []
        for i, clip in enumerate(clips):
            out = tmp / f"clip_{i:03d}.mp4"
            self.prepare_clip(clip, duration=5, output=out)
            prepared.append(out)

        # 2. Concat
        concat_out = tmp / "concat.mp4"
        if len(prepared) > 1:
            self.concat_clips(prepared, concat_out)
        else:
            _shutil.copy2(str(prepared[0]), str(concat_out))

        # 3. Emotional paragraph overlay centered on screen
        text_out = tmp / "with_text.mp4"
        self.add_paragraph_overlay(concat_out, hook_text, text_out)

        # 4. Music as sole audio
        if music_path and music_path.exists():
            self.add_music_only(text_out, music_path, output_path)
        else:
            _shutil.move(str(text_out), str(output_path))

        log.info("Video silencioso final: %s", output_path)

        for f in tmp.glob("*.mp4"):
            try:
                f.unlink()
            except Exception:
                pass

        return output_path


editor = VideoEditor()
