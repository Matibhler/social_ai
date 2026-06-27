"""
Análisis de patrones de contenido usando LLM local.
"""

from collections import Counter
from datetime import datetime
from statistics import mean

from core.database import get_session
from core.llm import llm
from core.logger import get_logger
from core.models import (
    CompetitorAccount, CompetitorAnalysis, CompetitorPost, Platform
)

log = get_logger(__name__)

ANALYSIS_SYSTEM = """
Eres un estratega de contenido para redes sociales.
Analiza los datos proporcionados y responde con JSON válido.
Sé específico, basado en datos y orientado a oportunidades accionables.
"""


def analyze_account(account_id: int) -> CompetitorAnalysis:
    """Analiza todos los posts de una cuenta y genera insights."""
    with get_session() as db:
        account = db.get(CompetitorAccount, account_id)
        if not account:
            raise ValueError(f"Cuenta {account_id} no encontrada")

        posts = (
            db.query(CompetitorPost)
            .filter_by(account_id=account_id)
            .all()
        )
        if not posts:
            raise ValueError("No hay posts para analizar")

        log.info("Analizando %d posts de @%s", len(posts), account.username)

        # ── Métricas estadísticas ──────────────────────────────────────────
        durations = [p.duration_seconds for p in posts if p.duration_seconds]
        avg_duration = mean(durations) if durations else 0

        format_counts = Counter(p.content_format for p in posts if p.content_format)
        top_formats = [{"format": f, "count": c} for f, c in format_counts.most_common(5)]

        all_hashtags = []
        for p in posts:
            if p.hashtags:
                all_hashtags.extend(p.hashtags)
        top_hashtags = [{"tag": t, "count": c} for t, c in Counter(all_hashtags).most_common(20)]

        hooks = [p.hook_text for p in posts if p.hook_text]
        ctas = [p.cta_text for p in posts if p.cta_text]

        # ── Análisis LLM ──────────────────────────────────────────────────
        posts_summary = "\n".join(
            f"- [{p.content_format}] Views:{p.views} Likes:{p.likes} "
            f"Hook: '{p.hook_text[:80]}' CTA: '{p.cta_text[:60]}'"
            for p in posts[:30]
        )

        prompt = f"""
Analiza estos {len(posts)} posts de @{account.username} (nicho: {account.niche}):

{posts_summary}

Hooks más usados:
{chr(10).join(hooks[:10])}

CTAs más usados:
{chr(10).join(ctas[:10])}

Devuelve JSON con esta estructura exacta:
{{
  "common_hooks": ["hook1", "hook2", "hook3"],
  "common_ctas": ["cta1", "cta2"],
  "best_posting_hours": [18, 19, 20],
  "posting_frequency_per_week": 5.0,
  "content_gaps": [
    "Oportunidad 1: tema poco cubierto",
    "Oportunidad 2: formato no explorado"
  ],
  "key_insights": "Resumen de 2-3 oraciones con las observaciones más importantes"
}}
"""
        try:
            analysis_data = llm.json_generate(prompt, system=ANALYSIS_SYSTEM)
        except Exception as e:
            log.error("Error en análisis LLM: %s", e)
            analysis_data = {
                "common_hooks": hooks[:3],
                "common_ctas": ctas[:2],
                "best_posting_hours": [18, 19, 20],
                "posting_frequency_per_week": 5.0,
                "content_gaps": ["Análisis LLM no disponible"],
                "key_insights": "Análisis estadístico básico completado.",
            }

        # ── Guardar análisis ───────────────────────────────────────────────
        analysis = CompetitorAnalysis(
            account_id=account_id,
            analyzed_at=datetime.utcnow(),
            top_formats=top_formats,
            avg_duration=avg_duration,
            posting_frequency_per_week=analysis_data.get("posting_frequency_per_week", 0),
            best_posting_hours=analysis_data.get("best_posting_hours", []),
            common_hooks=analysis_data.get("common_hooks", []),
            common_ctas=analysis_data.get("common_ctas", []),
            top_hashtags=top_hashtags,
            content_gaps=analysis_data.get("content_gaps", []),
        )
        db.add(analysis)
        db.commit()

        log.info("Análisis guardado para @%s", account.username)
        return analysis


def find_content_opportunities(niche: str) -> list[str]:
    """Cruza análisis de múltiples cuentas para encontrar gaps globales."""
    with get_session() as db:
        accounts = db.query(CompetitorAccount).filter_by(niche=niche).all()
        all_gaps = []
        for acc in accounts:
            latest = (
                db.query(CompetitorAnalysis)
                .filter_by(account_id=acc.id)
                .order_by(CompetitorAnalysis.analyzed_at.desc())
                .first()
            )
            if latest and latest.content_gaps:
                all_gaps.extend(latest.content_gaps)

    if not all_gaps:
        return []

    prompt = f"""
Nicho: {niche}

Estas son oportunidades de contenido detectadas al analizar cuentas competidoras:
{chr(10).join(f'- {g}' for g in all_gaps)}

Consolida y prioriza las TOP 5 oportunidades más accionables.
Devuelve JSON: {{"opportunities": ["op1", "op2", "op3", "op4", "op5"]}}
"""
    try:
        result = llm.json_generate(prompt, system=ANALYSIS_SYSTEM)
        return result.get("opportunities", all_gaps[:5])
    except Exception:
        return all_gaps[:5]
