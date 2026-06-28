"""
Editor cinematografico para reels virales.
Produce videos con Ken Burns, color grading, intro animada y subtitulos cinematograficos.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from content.video_editor import VideoEditor, run_ffmpeg
from content.cinematic_analyzer import CinematicPlan
from core.config import settings
from core.logger import get_logger

log = get_logger(__name__)

W = settings.VIDEO_WIDTH    # 1080
H = settings.VIDEO_HEIGHT   # 1920
FPS = settings.VIDEO_FPS    # 30

# Pre-scale for Ken Burns: 25% extra zoom room
_KB_W = (int(W * 1.25) // 2) * 2   # 1350 → even
_KB_H = (int(H * 1.25) // 2) * 2   # 2400 → even


def _find_font() -> str:
    """Return a Windows font path with the drive-letter colon escaped for FFmpeg filter syntax."""
    win_dir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for name in ("arialbd.ttf", "arial.ttf", "tahoma.ttf"):
        candidate = win_dir / "Fonts" / name
        if candidate.exists():
            # Forward slashes + escaped colon so FFmpeg filter parser doesn't split on ':'
            return str(candidate).replace("\\", "/").replace(":", "\\:")
    return ""


def _audio_duration(audio_path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return 45.0


class CinematicEditor(VideoEditor):
    """
    Extends VideoEditor with cinematic effects:
    - Animated intro card (black bg + text)
    - Ken Burns zoom per clip
    - Color grading (warm, high contrast, vignette, grain)
    - Letterbox bars (documentary mode)
    - Single-pass subtitle burn + color grade
    """

    def __init__(self):
        self._font = _find_font()

    def _font_opt(self) -> str:
        return f":fontfile='{self._font}'" if self._font else ""

    def make_intro(
        self,
        text: str,
        keyword: str,
        output: Path,
        duration: float = 3.0,
    ) -> Path:
        """
        3-second black-bg intro card.
        Top line: full intro text in white (fade + upward slide).
        Bottom line: keyword in gold, slightly larger.
        """
        def _esc(t: str) -> str:
            return t.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")

        safe_text = _esc(text.upper())
        safe_kw = _esc(keyword.upper())
        font_opt = self._font_opt()

        # Alpha: fade in 0-0.5s, hold, fade out 2.5-3s
        alpha = "if(lt(t,0.5),t/0.5,if(lt(t,2.5),1,if(lt(t,3),(3-t)/0.5,0)))"
        # Vertical slide: 60px below center at t=0, reaches center at t=0.5
        slide = "60*(1-if(lt(t,0.5),t/0.5,1))"

        main_y = f"(h-text_h)/2-70+{slide}"
        kw_y = f"(h-text_h)/2+30+{slide}"

        # y expressions must be single-quoted — they contain commas inside if()
        # which FFmpeg would otherwise treat as filter chain separators
        main_filter = (
            f"drawtext=text='{safe_text}'{font_opt}"
            f":fontsize=68:fontcolor=white"
            f":alpha='{alpha}':x=(w-text_w)/2:y='{main_y}'"
            f":shadowcolor=black@0.6:shadowx=3:shadowy=3"
        )
        kw_filter = (
            f"drawtext=text='{safe_kw}'{font_opt}"
            f":fontsize=90:fontcolor=0xFFD700"
            f":alpha='{alpha}':x=(w-text_w)/2:y='{kw_y}'"
            f":shadowcolor=black@0.8:shadowx=4:shadowy=4"
        )

        output.parent.mkdir(parents=True, exist_ok=True)
        run_ffmpeg(
            "-f", "lavfi",
            "-i", f"color=c=black:size={W}x{H}:rate={FPS}",
            "-t", str(duration),
            "-vf", f"{main_filter},{kw_filter}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-an",
            str(output),
        )
        return output

    def prepare_clip_cinematic(
        self,
        video_path: Path,
        duration: float,
        output: Path,
        zoom_direction: str = "in",
        slow_motion: bool = False,
    ) -> Path:
        """
        One FFmpeg pass: normalize aspect ratio, pre-scale for Ken Burns,
        optional slow motion, then zoompan to final 1080x1920.
        """
        # For slow motion: read half the duration, then setpts doubles playback time
        source_duration = duration / 2.0 if slow_motion else duration
        output_frames = max(int(duration * FPS), FPS)  # at least 1 second
        increment = 0.25 / output_frames

        if zoom_direction == "in":
            z_expr = f"min(zoom+{increment:.8f},1.25)"
        elif zoom_direction == "out":
            z_expr = f"if(eq(on,1),1.25,max(zoom-{increment:.8f},1.0))"
        else:
            z_expr = "1.0"

        # Center pan
        x_expr = "(iw-iw/zoom)/2"
        y_expr = "(ih-ih/zoom)/2"

        filters = [
            # Normalize to pre-scale dimensions
            f"scale={_KB_W}:{_KB_H}:force_original_aspect_ratio=increase",
            f"crop={_KB_W}:{_KB_H}",
        ]

        if slow_motion:
            filters.append("setpts=2.0*PTS")

        if zoom_direction != "none":
            filters.append(
                f"zoompan=z='{z_expr}':d={output_frames}"
                f":x='{x_expr}':y='{y_expr}':s={W}x{H}:fps={FPS}"
            )
        else:
            filters.append(f"scale={W}:{H}")
            filters.append(f"fps={FPS}")

        output.parent.mkdir(parents=True, exist_ok=True)
        run_ffmpeg(
            "-i", str(video_path),
            "-t", str(source_duration),
            "-vf", ",".join(filters),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-an",
            str(output),
        )
        return output

    def apply_color_grade(
        self,
        video_path: Path,
        output: Path,
        subtitle_path: Optional[Path] = None,
        letterbox: bool = False,
    ) -> Path:
        """
        Single FFmpeg pass:
        warm color grade + vignette + grain + optional subtitles + optional letterbox bars.
        Order: grade → subtitles → bars (bars render on top, hiding bottom caption area).
        """
        filters = [
            # Warm tones + contrast + saturation
            "eq=contrast=1.2:brightness=0.02:saturation=1.1",
            "colorbalance=rs=0.05:gs=-0.02:bs=-0.08:rm=0.03:gm=-0.01:bm=-0.05",
            # Vignette (~45 degree falloff)
            "vignette=PI/4",
            # Subtle film grain (temporal+uniform)
            "noise=alls=8:allf=t+u",
        ]

        cwd = None
        if subtitle_path and subtitle_path.exists():
            # Filename-only + cwd= avoids Windows drive-letter colon in filter string
            filters.append(f"ass={subtitle_path.name}")
            cwd = str(subtitle_path.parent)

        if letterbox:
            # 140px black bars — rendered AFTER subtitles so bars cover bottom area
            # ASS MarginV=60 keeps text above bar
            filters.append("drawbox=x=0:y=0:w=iw:h=140:color=black:t=fill")
            filters.append(f"drawbox=x=0:y=ih-140:w=iw:h=140:color=black:t=fill")

        output.parent.mkdir(parents=True, exist_ok=True)
        run_ffmpeg(
            "-i", str(video_path),
            "-vf", ",".join(filters),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            str(output),
            cwd=cwd,
        )
        return output

    def cinematic_pipeline(
        self,
        clips: list[Path],
        audio_path: Path,
        subtitle_path: Optional[Path],
        hook_text: str,
        output_path: Path,
        plan: CinematicPlan,
        music_path: Optional[Path] = None,
        progress_cb=None,
    ) -> Path:
        """
        Full cinematic pipeline:
        intro → per-clip Ken Burns → concat → add audio → color grade+subs → music
        """
        tmp = output_path.parent / "tmp"
        tmp.mkdir(exist_ok=True)

        audio_dur = _audio_duration(audio_path)
        n_clips = len(clips)
        intro_dur = 3.0

        # Distribute remaining time evenly across clips, floor at 4s for zoompan
        clip_dur = (audio_dur - intro_dur) / max(n_clips, 1)
        clip_dur = max(clip_dur, 4.0)

        log.info(
            "Pipeline cinematografico: %d clips x %.1fs | intro=%.1fs | audio=%.1fs",
            n_clips, clip_dur, intro_dur, audio_dur,
        )

        def _cb(stage, clip_index=-1):
            if progress_cb:
                progress_cb(stage, clip_index)

        # 1. Cinematic intro
        _cb("intro")
        intro_out = tmp / "intro.mp4"
        self.make_intro(plan.intro_text, plan.intro_keyword, intro_out, duration=intro_dur)

        # 2. Per-clip: Ken Burns + optional slow motion
        prepared = [intro_out]
        for i, clip_path in enumerate(clips):
            directive = plan.clip_directives[i] if i < len(plan.clip_directives) else None
            zoom_dir = directive.zoom_direction if directive else ("in" if i % 2 == 0 else "out")
            slow_mo = directive.slow_motion if directive else False

            _cb("Aplicando zoom cinematográfico al clip", i)
            clip_out = tmp / f"clip_{i:03d}.mp4"
            self.prepare_clip_cinematic(clip_path, clip_dur, clip_out, zoom_dir, slow_mo)
            prepared.append(clip_out)

        # 3. Concatenate (copy mux — no re-encode)
        _cb("concat")
        concat_out = tmp / "concat.mp4"
        if len(prepared) > 1:
            self.concat_clips(prepared, concat_out)
        else:
            shutil.copy2(str(prepared[0]), str(concat_out))

        # 4. Add TTS narration (re-encodes once to attach audio)
        _cb("audio")
        with_audio = tmp / "with_audio.mp4"
        self.add_audio(concat_out, audio_path, with_audio, loop_video=False)

        # 5. Color grade + subtitles + letterbox (single pass)
        _cb("grade")
        graded_out = tmp / "graded.mp4"
        self.apply_color_grade(
            with_audio, graded_out,
            subtitle_path=subtitle_path,
            letterbox=plan.show_letterbox,
        )

        # 6. Background music (inherited method; -c:v copy = no video re-encode)
        if music_path and music_path.exists():
            _cb("music")
            final_tmp = tmp / "with_music.mp4"
            self.add_background_music(graded_out, music_path, final_tmp)
        else:
            final_tmp = graded_out

        # 7. Move to final destination
        shutil.move(str(final_tmp), str(output_path))
        log.info("Video cinematografico final: %s", output_path)

        # Cleanup intermediates
        for f in tmp.glob("*.mp4"):
            f.unlink(missing_ok=True)
        for f in tmp.glob("*.txt"):
            f.unlink(missing_ok=True)

        return output_path
