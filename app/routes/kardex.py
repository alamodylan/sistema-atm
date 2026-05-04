from datetime import datetime, time

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import login_required
from app.services.kardex_service import get_all_warehouses

from app.services.kardex_service import (
    KardexServiceError,
    get_article_by_code_or_barcode,
    get_kardex_data,
    get_kardex_warehouses_for_site,
)


kardex_bp = Blueprint(
    "kardex",
    __name__,
    url_prefix="/kardex",
)


@kardex_bp.route("/", methods=["GET"])
@login_required
def index():
    site_id = session.get("active_site_id")

    if not site_id:
        flash("Debe seleccionar un predio activo.", "warning")
        return redirect(url_for("dashboard.index"))

    warehouses = get_all_warehouses()

    selected_warehouse_id = request.args.get("warehouse_id", type=int)
    code = request.args.get("code", "", type=str).strip()
    date_from_raw = request.args.get("date_from", "", type=str).strip()
    date_to_raw = request.args.get("date_to", "", type=str).strip()

    kardex = None
    article = None

    if selected_warehouse_id or code or date_from_raw or date_to_raw:
        if not selected_warehouse_id:
            flash("Debe seleccionar una bodega.", "warning")
            return render_template(
                "reports/kardex.html",
                warehouses=warehouses,
                selected_warehouse_id=selected_warehouse_id,
                code=code,
                date_from=date_from_raw,
                date_to=date_to_raw,
                kardex=kardex,
                article=article,
            )

        if not code:
            flash("Debe ingresar el código del artículo.", "warning")
            return render_template(
                "reports/kardex.html",
                warehouses=warehouses,
                selected_warehouse_id=selected_warehouse_id,
                code=code,
                date_from=date_from_raw,
                date_to=date_to_raw,
                kardex=kardex,
                article=article,
            )

        if not date_from_raw or not date_to_raw:
            flash("Debe seleccionar el rango de fechas.", "warning")
            return render_template(
                "reports/kardex.html",
                warehouses=warehouses,
                selected_warehouse_id=selected_warehouse_id,
                code=code,
                date_from=date_from_raw,
                date_to=date_to_raw,
                kardex=kardex,
                article=article,
            )

        try:
            date_from = datetime.combine(
                datetime.strptime(date_from_raw, "%Y-%m-%d").date(),
                time.min,
            )

            date_to = datetime.combine(
                datetime.strptime(date_to_raw, "%Y-%m-%d").date(),
                time.max,
            )

            article = get_article_by_code_or_barcode(code)

            kardex = get_kardex_data(
                site_id=site_id,
                warehouse_id=selected_warehouse_id,
                article_id=article.id,
                date_from=date_from,
                date_to=date_to,
            )

        except ValueError:
            flash("El formato de fecha no es válido.", "danger")

        except KardexServiceError as exc:
            flash(str(exc), "danger")

    return render_template(
        "reports/kardex.html",
        warehouses=warehouses,
        selected_warehouse_id=selected_warehouse_id,
        code=code,
        date_from=date_from_raw,
        date_to=date_to_raw,
        kardex=kardex,
        article=article,
    )