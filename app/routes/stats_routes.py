from flask import Blueprint, render_template, request, session
from flask_login import login_required

from app.services.stats_service import get_mechanics_stats
from app.models.site import Site


stats_bp = Blueprint(
    "stats",
    __name__,
    url_prefix="/stats",
)


@stats_bp.route("/", methods=["GET"])
@login_required
def index():
    # 🔹 Predio activo (como todo tu sistema)
    active_site_id = session.get("active_site_id")

    # 🔹 Permitir cambiar predio en estadísticas
    selected_site_id = request.args.get("site_id", type=int)

    if not selected_site_id:
        selected_site_id = active_site_id

    # 🔹 Obtener datos
    stats = get_mechanics_stats(site_id=selected_site_id)

    # 🔹 Ordenamientos
    best_mechanics = sorted(stats, key=lambda x: x["avg_seconds"])[:5]
    worst_mechanics = sorted(stats, key=lambda x: x["avg_seconds"], reverse=True)[:5]

    # 🔹 Preparar datos para gráficos
    chart_labels = [m["name"] for m in stats]
    chart_avg = [m["avg_seconds"] for m in stats]
    chart_jobs = [m["total_jobs"] for m in stats]

    # 🔹 Predios para selector
    sites = Site.query.order_by(Site.name.asc()).all()

    return render_template(
        "stats/index.html",
        stats=stats,
        best_mechanics=best_mechanics,
        worst_mechanics=worst_mechanics,
        chart_labels=chart_labels,
        chart_avg=chart_avg,
        chart_jobs=chart_jobs,
        sites=sites,
        selected_site_id=selected_site_id,
    )