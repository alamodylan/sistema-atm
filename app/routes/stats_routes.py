from datetime import datetime, time

from flask import Blueprint, flash, render_template, request, session
from flask_login import login_required

from app.models.site import Site
from app.services.stats_service import (
    get_mechanics_for_filter,
    get_mechanics_stats,
    get_repair_type_stats,
    get_repair_types_for_filter,
)


stats_bp = Blueprint(
    "stats",
    __name__,
    url_prefix="/stats",
)


@stats_bp.route("/", methods=["GET"])
@login_required
def index():
    active_site_id = session.get("active_site_id")

    selected_site_id = request.args.get("site_id", type=int)
    selected_mechanic_id = request.args.get("mechanic_id", type=int)
    selected_repair_type_id = request.args.get("repair_type_id", type=int)

    date_from_raw = request.args.get("date_from", "", type=str).strip()
    date_to_raw = request.args.get("date_to", "", type=str).strip()

    if not selected_site_id:
        selected_site_id = active_site_id

    date_from = None
    date_to = None

    try:
        if date_from_raw:
            date_from = datetime.combine(
                datetime.strptime(date_from_raw, "%Y-%m-%d").date(),
                time.min,
            )

        if date_to_raw:
            date_to = datetime.combine(
                datetime.strptime(date_to_raw, "%Y-%m-%d").date(),
                time.max,
            )

    except ValueError:
        flash("El rango de fechas no tiene un formato válido.", "danger")
        date_from = None
        date_to = None

    stats = get_mechanics_stats(
        site_id=selected_site_id,
        mechanic_id=selected_mechanic_id,
        repair_type_id=selected_repair_type_id,
        date_from=date_from,
        date_to=date_to,
    )

    repair_type_stats = get_repair_type_stats(
        site_id=selected_site_id,
        mechanic_id=selected_mechanic_id,
        repair_type_id=selected_repair_type_id,
        date_from=date_from,
        date_to=date_to,
    )

    best_mechanics = sorted(stats, key=lambda x: x["avg_seconds"])[:5]
    worst_mechanics = sorted(stats, key=lambda x: x["avg_seconds"], reverse=True)[:5]

    chart_labels = [m["name"] for m in stats]
    chart_avg = [m["avg_seconds"] for m in stats]
    chart_jobs = [m["total_jobs"] for m in stats]

    repair_type_chart_labels = [
        item["repair_type_name"] for item in repair_type_stats
    ]

    repair_type_chart_avg = [
        item["avg_seconds"] for item in repair_type_stats
    ]

    repair_type_chart_jobs = [
        item["total_jobs"] for item in repair_type_stats
    ]

    total_jobs = sum(m["total_jobs"] for m in stats)
    total_work_orders = sum(m["total_work_orders"] for m in stats)
    total_seconds = sum(m["total_seconds"] for m in stats)

    sites = Site.query.order_by(Site.name.asc()).all()
    mechanics = get_mechanics_for_filter(site_id=selected_site_id)
    repair_types = get_repair_types_for_filter()

    return render_template(
        "stats/index.html",
        stats=stats,
        repair_type_stats=repair_type_stats,
        best_mechanics=best_mechanics,
        worst_mechanics=worst_mechanics,
        chart_labels=chart_labels,
        chart_avg=chart_avg,
        chart_jobs=chart_jobs,
        repair_type_chart_labels=repair_type_chart_labels,
        repair_type_chart_avg=repair_type_chart_avg,
        repair_type_chart_jobs=repair_type_chart_jobs,
        total_jobs=total_jobs,
        total_work_orders=total_work_orders,
        total_seconds=total_seconds,
        sites=sites,
        mechanics=mechanics,
        repair_types=repair_types,
        selected_site_id=selected_site_id,
        selected_mechanic_id=selected_mechanic_id,
        selected_repair_type_id=selected_repair_type_id,
        date_from=date_from_raw,
        date_to=date_to_raw,
    )