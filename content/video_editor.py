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

    def prepare_clip(self, video_path: Path, duration: float, output: Path) -> Path:
        """Recorta y escala un clip al formato vertical 1080x1920."""
        run_ffmpeg(
            "-i", str(video_path),
            "-t", str(duration),
            "-vf", (
                f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},"
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

        # 1. Preparar clips con cortes rápidos (3 segundos cada uno)
        prepared = []
        for i, clip in enumerate(clips):
            out = tmp / f"clip_{i:03d}.mp4"
            self.prepare_clip(clip, duration=3, output=out)
            prepared.append(out)

        # 2. Añadir fade transition entre clips (0.3s crossfade)
        fade_dur = 0.3
        if len(prepared) > 1:
            current = prepared[0]
            for i, next_clip in enumerate(prepared[1:], 1):
                faded = tmp / f"faded_{i:03d}.mp4"
                dur_a = _get_duration(current)
                offset = max(0.01, dur_a - fade_dur)
                run_ffmpeg(
                    "-i", str(current), "-i", str(next_clip),
                    "-filter_complex",
                    f"[0:v][1:v]xfade=transition=fade:duration={fade_dur}:offset={offset}[v]",
                    "-map", "[v]",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    str(faded),
                )
                current = faded
            concat_out = current
        else:
            concat_out = tmp / "concat.mp4"
            prepared[0].rename(concat_out)

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

        # Limpiar temporales
        for f in tmp.glob("*.mp4"):
            f.unlink(missing_ok=True)

        return output_path


editor = VideoEditor()
