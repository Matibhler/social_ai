"""
Generación de reportes HTML/Markdown a partir de análisis de competencia.
"""

import json
from datetime import datetime
from pathlib import Path

from core.config import settings
from core.database import get_session
from core.logger import get_logger
from core.models import CompetitorAccount, CompetitorAnalysis, CompetitorPost

log = get_logger(__name__)

REPORT_DIR = settings.DATA_DIR / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def generate_html_report(account_id: int) -> Path:
    """Genera reporte HTML visual de una cuenta analizada."""
    with get_session() as db:
        account = db.get(CompetitorAccount, account_id)
        analysis = (
            db.query(CompetitorAnalysis)
            .filter_by(account_id=account_id)
            .order_by(CompetitorAnalysis.analyzed_at.desc())
            .first()
        )
        posts = (
            db.query(CompetitorPost)
            .filter_by(account_id=account_id)
            .order_by(CompetitorPost.views.desc())
            .limit(10)
            .all()
        )

    if not account or not analysis:
        raise ValueError("Cuenta o análisis no encontrado")

    top_posts_html = ""
    for p in posts:
        top_posts_html += f"""
        <tr>
          <td><a href="{p.url}" target="_blank">{p.post_id[:20]}…</a></td>
          <td>{p.content_format}</td>
          <td>{p.views:,}</td>
          <td>{p.likes:,}</td>
          <td>{p.hook_text[:60]}…</td>
        </tr>"""

    hooks_html = "".join(
        f"<li><code>{h}</code></li>"
        for h in (analysis.common_hooks or [])
    )
    gaps_html = "".join(
        f"<li>✅ {g}</li>"
        for g in (analysis.content_gaps or [])
    )
    hashtags_html = " ".join(
        f'<span class="badge">#{t["tag"]} ({t["count"]})</span>'
        for t in (analysis.top_hashtags or [])[:15]
    )

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Reporte: @{account.username}</title>
  <style>
    body {{ font-family: 'Segoe UI', sans-serif; background:#f5f5f5; color:#222; margin:0; }}
    .container {{ max-width:960px; margin:0 auto; padding:2rem; }}
    h1 {{ color:#6c3483; }} h2 {{ color:#1a5276; border-bottom:2px solid #aed6f1; padding-bottom:.3rem; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:1.5rem; }}
    .card {{ background:#fff; border-radius:10px; padding:1.5rem; box-shadow:0 2px 8px rgba(0,0,0,.1); }}
    table {{ width:100%; border-collapse:collapse; }}
    th {{ background:#1a5276; color:#fff; padding:.5rem; }}
    td {{ padding:.5rem; border-bottom:1px solid #eee; }}
    .badge {{ background:#2e86c1; color:#fff; border-radius:12px;
              padding:.2rem .6rem; font-size:.8rem; margin:.2rem; display:inline-block; }}
    li {{ margin:.4rem 0; }}
  </style>
</head>
<body>
<div class="container">
  <h1>📊 Análisis de Competencia: @{account.username}</h1>
  <p>Plataforma: <strong>{account.platform}</strong> | Seguidores: <strong>{account.followers:,}</strong>
     | Nicho: <strong>{account.niche}</strong> | Analizado: {analysis.analyzed_at.strftime('%Y-%m-%d %H:%M')}</p>

  <div class="grid">
    <div class="card">
      <h2>📈 Métricas Clave</h2>
      <ul>
        <li>Duración promedio de video: <strong>{analysis.avg_duration:.0f}s</strong></li>
        <li>Publicaciones/semana: <strong>{analysis.posting_frequency_per_week:.1f}</strong></li>
        <li>Mejores horas: <strong>{', '.join(str(h)+'h' for h in (analysis.best_posting_hours or []))}</strong></li>
      </ul>
      <h2>🎞️ Formatos Top</h2>
      <ul>{''.join(f"<li>{f['format']}: {f['count']} posts</li>" for f in (analysis.top_formats or []))}</ul>
    </div>
    <div class="card">
      <h2>🪝 Hooks más efectivos</h2>
      <ul>{hooks_html}</ul>
    </div>
  </div>

  <div class="card" style="margin-top:1.5rem;">
    <h2>🚀 Oportunidades de contenido</h2>
    <ul>{gaps_html}</ul>
  </div>

  <div class="card" style="margin-top:1.5rem;">
    <h2>🏷️ Hashtags más usados</h2>
    <p>{hashtags_html}</p>
  </div>

  <div class="card" style="margin-top:1.5rem;">
    <h2>🔥 Top 10 Posts</h2>
    <table>
      <tr><th>ID</th><th>Formato</th><th>Views</th><th>Likes</th><th>Hook</th></tr>
      {top_posts_html}
    </table>
  </div>

  <p style="text-align:center;color:#aaa;margin-top:2rem;">
    Generado por Social AI · {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
  </p>
</div>
</body>
</html>"""

    report_path = REPORT_DIR / f"report_{account.username}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.html"
    report_path.write_text(html, encoding="utf-8")
    log.info("Reporte generado: %s", report_path)
    return report_path
