"""
Generación de guiones de video usando LLM local.
"""

from core.config import settings
from core.database import get_session
from core.llm import llm
from core.logger import get_logger
from core.models import ContentPiece, ContentStatus, Platform

log = get_logger(__name__)

SCRIPT_SYSTEM = f"""
Eres un guionista experto en contenido viral para redes sociales.
Marca: {settings.BRAND_NAME}
Voz de marca: {settings.BRAND_VOICE}
Nicho: {settings.NICHE}

Crea guiones que:
- Capturen atención en los primeros 3 segundos (hook poderoso)
- Sean naturales y conversacionales
- Tengan un CTA claro al final
- Estén optimizados para video vertical (Reels, Shorts, TikTok)
"""


def generate_script(
    topic: str,
    format: str = "tutorial",
    platform: Platform = Platform.INSTAGRAM,
    target_duration: int = 45,
    content_gaps: list[str] | None = None,
) -> ContentPiece:
    """Genera un guión completo y lo guarda en la DB."""

    gaps_context = ""
    if content_gaps:
        gaps_context = f"\nOportunidades detectadas en la competencia:\n" + "\n".join(
            f"- {g}" for g in content_gaps
        )

    prompt = f"""
Crea un guión de video para {platform.value} sobre: "{topic}"

Formato: {format}
Duración objetivo: {target_duration} segundos
{gaps_context}

El video es vertical (9:16), sin cámara, solo voz en off con B-roll.

Responde en JSON:
{{
  "title": "Título del video",
  "hook": "Primeras 2-3 oraciones que capturan la atención (máx 15 seg)",
  "body": [
    {{"text": "Segmento 1 del guión", "duration_hint": 10, "visual_note": "Mostrar..."}},
    {{"text": "Segmento 2 del guión", "duration_hint": 15, "visual_note": "Mostrar..."}}
  ],
  "cta": "Llamado a la acción final (5-7 seg)",
  "hashtags": ["#tag1", "#tag2", "#tag3"],
  "thumbnail_text": "Texto para la miniatura (máx 6 palabras)"
}}
"""
    log.info("Generando guión para: '%s'", topic)
    data = llm.json_generate(prompt, system=SCRIPT_SYSTEM)

    # Construir texto completo del guión
    body_text = " ".join(seg["text"] for seg in data.get("body", []))
    full_script = f"{data['hook']}\n\n{body_text}\n\n{data['cta']}"

    with get_session() as db:
        piece = ContentPiece(
            title=data["title"],
            script=full_script,
            hook=data["hook"],
            cta=data["cta"],
            niche=settings.NICHE,
            format=format,
            target_platform=platform,
            status=ContentStatus.DRAFT,
            hashtags=data.get("hashtags", []),
        )
        db.add(piece)
        db.commit()
        db.refresh(piece)
        db.expunge(piece)
        log.info("Guión creado: ID=%d '%s'", piece.id, piece.title)
        return piece


def generate_batch(topics: list[str], platform: Platform = Platform.INSTAGRAM) -> list[ContentPiece]:
    """Genera múltiples guiones en batch."""
    pieces = []
    for topic in topics:
        try:
            p = generate_script(topic, platform=platform)
            pieces.append(p)
        except Exception as e:
            log.error("Error generando guión para '%s': %s", topic, e)
    return pieces


def suggest_topics(niche: str, count: int = 10) -> list[str]:
    """Sugiere temas virales para un nicho dado."""
    prompt = f"""
Sugiere {count} temas de video viral para el nicho: "{niche}"

Criterios:
- Alta demanda y bajo contenido (oportunidades)
- Útiles, entretenidos o inspiradores
- Aptos para video de 30-60 segundos

Devuelve JSON: {{"topics": ["tema1", "tema2", ...]}}
"""
    result = llm.json_generate(prompt, system=SCRIPT_SYSTEM)
    return result.get("topics", [])
