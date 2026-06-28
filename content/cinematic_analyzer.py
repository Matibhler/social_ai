"""
Analiza el guión con el LLM y produce un plan de edición cinematográfica.
"""

from dataclasses import dataclass, field

from core.llm import llm
from core.logger import get_logger

log = get_logger(__name__)


@dataclass
class ClipDirective:
    zoom_direction: str   # "in" | "out" | "none"
    slow_motion: bool


@dataclass
class CinematicPlan:
    intro_text: str
    intro_keyword: str
    show_letterbox: bool
    clip_directives: list[ClipDirective] = field(default_factory=list)

    @classmethod
    def default(cls, title: str, num_clips: int) -> "CinematicPlan":
        words = title.split()
        directives = [
            ClipDirective(
                zoom_direction="in" if i % 2 == 0 else "out",
                slow_motion=(i == 1),
            )
            for i in range(max(num_clips, 1))
        ]
        return cls(
            intro_text=" ".join(words[:7]) if words else "Lo que nadie te cuenta",
            intro_keyword=words[0] if words else "Hoy",
            show_letterbox=False,
            clip_directives=directives,
        )


def analyze_script_for_cinematic(
    script: str,
    title: str,
    num_clips: int,
) -> CinematicPlan:
    """LLM call that returns cinematic editing directives for the video."""
    num_clips = max(num_clips, 1)
    prompt = f"""Eres un editor de video viral experto en reels de Instagram y TikTok.
Analiza este guion y genera directivas de edicion cinematografica.

Titulo: {title}
Clips de B-roll disponibles: {num_clips}
Guion (primeros 400 caracteres): {script[:400]}

Responde UNICAMENTE con este JSON (sin texto extra):
{{
  "intro_text": "Frase impactante 4-7 palabras que engancha al espectador",
  "intro_keyword": "Unapalabra",
  "show_letterbox": false,
  "clip_directives": [
    {{"zoom_direction": "in", "slow_motion": false}}
  ]
}}

Reglas:
- intro_text: 4-7 palabras, frase gancho que genera curiosidad
- intro_keyword: exactamente UNA palabra que aparece en intro_text
- show_letterbox: true solo para contenido educativo/documental serio
- clip_directives: exactamente {num_clips} entradas
- zoom_direction: "in" para energia, "out" para revelacion dramatica, "none" para estabilidad
- slow_motion: true en maximo 1 clip para enfasis dramatico
"""
    try:
        data = llm.json_generate(prompt)

        raw = data.get("clip_directives", [])
        directives = [
            ClipDirective(
                zoom_direction=d.get("zoom_direction", "in"),
                slow_motion=bool(d.get("slow_motion", False)),
            )
            for d in raw[:num_clips]
        ]
        while len(directives) < num_clips:
            directives.append(ClipDirective("in" if len(directives) % 2 == 0 else "out", False))

        return CinematicPlan(
            intro_text=str(data.get("intro_text", title))[:80],
            intro_keyword=str(data.get("intro_keyword", title.split()[0] if title else "")).split()[0],
            show_letterbox=bool(data.get("show_letterbox", False)),
            clip_directives=directives,
        )
    except Exception as exc:
        log.warning("Analisis cinematografico LLM fallo (%s), usando defaults.", exc)
        return CinematicPlan.default(title, num_clips)
