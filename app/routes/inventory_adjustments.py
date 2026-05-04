from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from app.services.inventory_adjustment_service import (
    InventoryAdjustmentServiceError,
    create_inventory_adjustment,
    find_article_for_adjustment,
    get_adjustable_warehouses_for_site,
    get_adjustment_by_id,
    list_adjustments,
)

inventory_adjustments_bp = Blueprint(
    "inventory_adjustments",
    __name__,
    url_prefix="/inventory-adjustments",
)


@inventory_adjustments_bp.route("/", methods=["GET"])
@login_required
def index():
    site_id = session.get("active_site_id")

    if not site_id:
        flash("Debe seleccionar un predio activo.", "warning")
        return redirect(url_for("dashboard.index"))

    warehouse_id = request.args.get("warehouse_id", type=int)

    warehouses = get_adjustable_warehouses_for_site(site_id)

    adjustments = list_adjustments(
        site_id=site_id,
        warehouse_id=warehouse_id,
        limit=100,
    )

    return render_template(
        "inventory_adjustments/index.html",
        warehouses=warehouses,
        adjustments=adjustments,
        selected_warehouse_id=warehouse_id,
    )


@inventory_adjustments_bp.route("/new", methods=["GET"])
@login_required
def new():
    site_id = session.get("active_site_id")

    if not site_id:
        flash("Debe seleccionar un predio activo.", "warning")
        return redirect(url_for("dashboard.index"))

    warehouses = get_adjustable_warehouses_for_site(site_id)

    return render_template(
        "inventory_adjustments/new.html",
        warehouses=warehouses,
    )


@inventory_adjustments_bp.route("/article-lookup", methods=["GET"])
@login_required
def article_lookup():
    warehouse_id = request.args.get("warehouse_id", type=int)
    code = request.args.get("code", "").strip()

    if not warehouse_id:
        return jsonify(
            {
                "ok": False,
                "message": "Debe seleccionar una bodega.",
            }
        ), 400

    try:
        article_data = find_article_for_adjustment(
            warehouse_id=warehouse_id,
            code_or_barcode=code,
        )

        return jsonify(
            {
                "ok": True,
                "article": {
                    "id": article_data["article_id"],
                    "code": article_data["code"],
                    "barcode": article_data["barcode"],
                    "name": article_data["name"],
                    "current_quantity": str(article_data["current_quantity"]),
                },
            }
        )

    except InventoryAdjustmentServiceError as exc:
        return jsonify(
            {
                "ok": False,
                "message": str(exc),
            }
        ), 400


@inventory_adjustments_bp.route("/", methods=["POST"])
@login_required
def create():
    site_id = session.get("active_site_id")

    if not site_id:
        flash("Debe seleccionar un predio activo.", "warning")
        return redirect(url_for("dashboard.index"))

    warehouse_id = request.form.get("warehouse_id", type=int)
    notes = request.form.get("notes")

    article_ids = request.form.getlist("article_id[]")
    quantity_afters = request.form.getlist("quantity_after[]")

    lines = []

    for article_id, quantity_after in zip(article_ids, quantity_afters):
        if not article_id:
            continue

        lines.append(
            {
                "article_id": int(article_id),
                "quantity_after": quantity_after,
            }
        )

    try:
        adjustment = create_inventory_adjustment(
            site_id=site_id,
            warehouse_id=warehouse_id,
            created_by_user_id=current_user.id,
            lines=lines,
            notes=notes,
        )

        flash(f"Ajuste {adjustment.number} creado correctamente.", "success")
        return redirect(
            url_for(
                "inventory_adjustments.show",
                adjustment_id=adjustment.id,
            )
        )

    except InventoryAdjustmentServiceError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("inventory_adjustments.new"))


@inventory_adjustments_bp.route("/<int:adjustment_id>", methods=["GET"])
@login_required
def show(adjustment_id):
    adjustment = get_adjustment_by_id(adjustment_id)

    lines = adjustment.lines.all() if hasattr(adjustment.lines, "all") else adjustment.lines

    return render_template(
        "inventory_adjustments/show.html",
        adjustment=adjustment,
        lines=lines,
    )