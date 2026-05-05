from datetime import datetime, time

from flask import Blueprint, flash, render_template, request, session
from flask_login import login_required

from app.models.site import Site
from app.services.stats_service_equipos import get_equipment_dashboard_data


equipment_stats_bp = Blueprint(
    "equipment_stats",
    __name__,
    url_prefix="/stats/equipos",
)


@equipment_stats_bp.route("/", methods=["GET"])
@login_required
def index():
    active_site_id = session.get("active_site_id")

    selected_site_id = request.args.get("site_id", type=int)

    if not selected_site_id:
        selected_site_id = active_site_id

    date_from_raw = request.args.get("date_from", "", type=str).strip()
    date_to_raw = request.args.get("date_to", "", type=str).strip()

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

    dashboard = get_equipment_dashboard_data(
        site_id=selected_site_id,
        date_from=date_from,
        date_to=date_to,
    )

    sites = Site.query.order_by(Site.name.asc()).all()

    return render_template(
        "stats/equipos.html",
        dashboard=dashboard,
        summary=dashboard["summary"],
        most_repaired=dashboard["most_repaired"],
        most_entered=dashboard["most_entered"],
        top_cost=dashboard["top_cost"],
        by_site=dashboard["by_site"],
        repair_types=dashboard["repair_types"],
        sites=sites,
        selected_site_id=selected_site_id,
        date_from=date_from_raw,
        date_to=date_to_raw,
    )