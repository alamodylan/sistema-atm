from flask import Blueprint, redirect, render_template, session, url_for
from flask_login import current_user, login_required

from app.models.inventory import WarehouseStock
from app.models.warehouse import Warehouse
from app.models.waste_act import WasteAct
from app.models.work_order import WorkOrder


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def home():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login_page"))
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/set-site/<int:site_id>")
@login_required
def set_site(site_id):
    session["active_site_id"] = site_id
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/dashboard")
@login_required
def index():
    active_site_id = session.get("active_site_id")

    try:
        if active_site_id:
            work_orders_in_process = WorkOrder.query.filter_by(
                site_id=active_site_id,
                status="EN_PROCESO",
            ).count()

            work_orders_finalized = WorkOrder.query.filter_by(
                site_id=active_site_id,
                status="FINALIZADA",
            ).count()

            work_orders_closed = WorkOrder.query.filter_by(
                site_id=active_site_id,
                status="CERRADA",
            ).count()

            waste_borrador = WasteAct.query.filter_by(
                site_id=active_site_id,
                status="BORRADOR",
            ).count()

            waste_registrada = WasteAct.query.filter_by(
                site_id=active_site_id,
                status="REGISTRADA",
            ).count()

            waste_impresa = WasteAct.query.filter_by(
                site_id=active_site_id,
                status="IMPRESA",
            ).count()

            waste_cerrada = WasteAct.query.filter_by(
                site_id=active_site_id,
                status="CERRADA",
            ).count()

            waste_cancelada = WasteAct.query.filter_by(
                site_id=active_site_id,
                status="CANCELADA",
            ).count()

            inventory_records = (
                WarehouseStock.query
                .join(Warehouse, Warehouse.id == WarehouseStock.warehouse_id)
                .filter(Warehouse.site_id == active_site_id)
                .count()
            )
        else:
            work_orders_in_process = 0
            work_orders_finalized = 0
            work_orders_closed = 0
            waste_borrador = 0
            waste_registrada = 0
            waste_impresa = 0
            waste_cerrada = 0
            waste_cancelada = 0
            inventory_records = 0

        return render_template(
            "dashboard/index.html",
            title="Dashboard",
            subtitle="Vista general del sistema y accesos rápidos.",
            work_orders_in_process=work_orders_in_process,
            work_orders_finalized=work_orders_finalized,
            work_orders_closed=work_orders_closed,
            waste_borrador=waste_borrador,
            waste_registrada=waste_registrada,
            waste_impresa=waste_impresa,
            waste_cerrada=waste_cerrada,
            waste_cancelada=waste_cancelada,
            inventory_records=inventory_records,
        )

    except Exception:
        return render_template(
            "dashboard/index.html",
            title="Dashboard",
            subtitle="Vista general del sistema y accesos rápidos.",
            work_orders_in_process=0,
            work_orders_finalized=0,
            work_orders_closed=0,
            waste_borrador=0,
            waste_registrada=0,
            waste_impresa=0,
            waste_cerrada=0,
            waste_cancelada=0,
            inventory_records=0,
        )