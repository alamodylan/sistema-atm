from datetime import datetime, time

from flask import Blueprint, flash, render_template, request
from flask_login import login_required

from app.extensions import db
from app.models.inventory import InventoryLedger
from app.models.work_order import WorkOrder
from app.models.waste_act import WasteAct
from app.models.article import Article
from app.models.warehouse import Warehouse


report_bp = Blueprint("reports", __name__)


# =========================================================
# HOME REPORTES
# =========================================================
@report_bp.route("/", methods=["GET"])
@login_required
def reports_home():
    return render_template(
        "reports/index.html",
        title="Reportes",
        subtitle="Acceda a los reportes principales del sistema.",
    )


# =========================================================
# MOVIMIENTOS DE INVENTARIO
# =========================================================
@report_bp.route("/inventory-movements", methods=["GET"])
@login_required
def inventory_movements_report():
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    article_code = (request.args.get("article_code") or "").strip()
    warehouse_id = (request.args.get("warehouse_id") or "").strip()
    page = request.args.get("page", 1, type=int)

    try:
        query = (
            InventoryLedger.query
            .join(Article, Article.id == InventoryLedger.article_id)
            .join(Warehouse, Warehouse.id == InventoryLedger.warehouse_id)
        )

        if date_from:
            parsed_date_from = datetime.combine(
                datetime.strptime(date_from, "%Y-%m-%d").date(),
                time.min,
            )

            query = query.filter(
                InventoryLedger.created_at >= parsed_date_from
            )

        if date_to:
            parsed_date_to = datetime.combine(
                datetime.strptime(date_to, "%Y-%m-%d").date(),
                time.max,
            )

            query = query.filter(
                InventoryLedger.created_at <= parsed_date_to
            )

        if article_code:
            query = query.filter(
                Article.code.ilike(f"%{article_code}%")
            )

        if warehouse_id:
            query = query.filter(
                InventoryLedger.warehouse_id == int(warehouse_id)
            )

        pagination = (
            query
            .order_by(InventoryLedger.created_at.desc())
            .paginate(
                page=page,
                per_page=30,
                error_out=False,
            )
        )

        movements = pagination.items

        warehouses = (
            Warehouse.query
            .order_by(Warehouse.name.asc())
            .all()
        )

        return render_template(
            "reports/inventory_movements.html",
            title="Reporte de movimientos de inventario",
            subtitle="Entradas y salidas por rango de fechas, artículo, predio o bodega.",
            movements=movements,
            pagination=pagination,
            warehouses=warehouses,
            date_from=date_from,
            date_to=date_to,
            article_code=article_code,
            warehouse_id=warehouse_id,
        )

    except Exception:
        db.session.rollback()

        flash("Error al cargar el reporte de movimientos.", "danger")

        return render_template(
            "reports/inventory_movements.html",
            title="Reporte de movimientos de inventario",
            subtitle="Entradas y salidas por rango de fechas, artículo, predio o bodega.",
            movements=[],
            pagination=None,
            warehouses=[],
            date_from=date_from,
            date_to=date_to,
            article_code=article_code,
            warehouse_id=warehouse_id,
        )


# =========================================================
# REPORTE DE ÓRDENES DE TRABAJO
# =========================================================
@report_bp.route("/work-orders", methods=["GET"])
@login_required
def work_orders_report():
    status = (request.args.get("status") or "").strip()

    try:
        query = WorkOrder.query

        if status:
            query = query.filter(WorkOrder.status == status)

        work_orders = (
            query
            .order_by(WorkOrder.created_at.desc())
            .limit(200)
            .all()
        )

        return render_template(
            "reports/work_orders.html",
            title="Reporte de órdenes de trabajo",
            subtitle="Historial, estados, tiempos, responsables y mecánicos.",
            work_orders=work_orders,
            status=status,
        )

    except Exception:
        db.session.rollback()

        flash("Error al cargar el reporte de OT.", "danger")

        return render_template(
            "reports/work_orders.html",
            work_orders=[],
            status=status,
        )


# =========================================================
# REPORTE DE ACTAS DE DESECHO
# =========================================================
@report_bp.route("/waste-acts", methods=["GET"])
@login_required
def waste_acts_report():
    status = (request.args.get("status") or "").strip()

    try:
        query = WasteAct.query

        if status:
            query = query.filter(WasteAct.status == status)

        waste_acts = (
            query
            .order_by(WasteAct.created_at.desc())
            .limit(200)
            .all()
        )

        return render_template(
            "reports/waste_acts.html",
            title="Reporte de actas de desecho",
            subtitle="Consulte actas generadas, estados y artículos incluidos.",
            waste_acts=waste_acts,
            status=status,
        )

    except Exception:
        db.session.rollback()

        flash("Error al cargar el reporte de actas.", "danger")

        return render_template(
            "reports/waste_acts.html",
            waste_acts=[],
            status=status,
        )