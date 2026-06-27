"""
Generación automática de subtítulos usando Whisper (local).
Produce archivos .srt y .ass para quemarlos en el video con FFmpeg.
"""

from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)


def transcribe_audio(audio_path: Path, language: str = "es") -> list[dict]:
    """
    Transcribe audio con Whisper y retorna segmentos con timestamps.
    Requiere: pip install openai-whisper
    """
    try:
        import whisper
    except ImportError:
        raise ImportError("Instala Whisper: pip install openai-whisper")

    model = whisper.load_model("base")
    log.info("Transcribiendo: %s", audio_path.name)
    result = model.transcribe(str(audio_path), language=language, word_timestamps=True)

    segments = []
    for seg in result["segments"]:
        segments.append({
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"].strip(),
        })
    return segments


def to_srt(segments: list[dict], output_path: Path) -> Path:
    """Genera archivo .srt desde segmentos."""
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{_fmt_time(seg['start'])} --> {_fmt_time(seg['end'])}")
        lines.append(seg["text"])
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("SRT generado: %s", output_path)
    return output_path


def to_ass(segments: list[dict], output_path: Path, style: str = "viral") -> Path:
    """
    Genera archivo .ass con estilo visual tipo 'subtítulos virales':
    texto grande, centrado, con sombra y color llamativo.
    """
    styles = {
        "viral": (
            "Style: Default,Arial Black,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
            "1,0,0,0,100,100,0,0,1,3,2,2,10,10,30,1"
        ),
        "minimal": (
            "Style: Default,Arial,36,&H00FFFFFF,&H000000FF,&H00000000,&H60000000,"
            "0,0,0,0,100,100,0,0,1,2,1,2,10,10,20,1"
        ),
    }
    chosen_style = styles.get(style, styles["viral"])

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
{chosen_style}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for seg in segments:
        start = _fmt_time_ass(seg["start"])
        end = _fmt_time_ass(seg["end"])
        text = seg["text"].replace("\n", "\\N")
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    output_path.write_text(header + "\n".join(events), encoding="utf-8")
    log.info("ASS generado: %s", output_path)
    return output_path


def _fmt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _fmt_time_ass(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"
