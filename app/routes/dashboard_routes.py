from flask import Blueprint, redirect, render_template, session, url_for
from flask_login import current_user, login_required

from app.models.inventory import WarehouseStock
from app.models.waste_act import WasteAct
from app.models.warehouse import Warehouse
from app.models.work_order import WorkOrder
from app.models.work_order_request import WorkOrderRequest

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

    if not active_site_id:
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
            work_orders_in_process_list=[],
        )

    try:
        active_site_id = int(active_site_id)

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

        work_orders_in_process_list = (
            WorkOrder.query
            .filter_by(
                site_id=active_site_id,
                status="EN_PROCESO",
            )
            .order_by(WorkOrder.created_at.desc())
            .all()
        )

        for ot in work_orders_in_process_list:
            semaforo = "GREEN"

            requests = ot.requests
            tool_loans = ot.tool_loans

            has_open_tool_loans = any(
                loan.loan_status == "PRESTADA"
                for loan in tool_loans
            )

            has_pending_request = False
            has_partial_request = False

            for req in requests:
                if not req.sent_to_warehouse_at:
                    continue

                req_lines = req.lines

                for line in req_lines:
                    if line.line_status == "ATENDIDA_PARCIAL":
                        has_partial_request = True

                    if line.line_status in ("SOLICITADA", "PRESTADA"):
                        has_pending_request = True

            if has_open_tool_loans:
                semaforo = "RED"
            elif has_partial_request:
                semaforo = "YELLOW"
            elif has_pending_request:
                semaforo = "RED"
            else:
                semaforo = "GREEN"

            ot.semaforo = semaforo

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
            work_orders_in_process_list=work_orders_in_process_list,
        )

    except Exception as exc:
        print(f"[DASHBOARD ERROR] {exc}")
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
            work_orders_in_process_list=[],
        )


@dashboard_bp.route("/dashboard/jefatura")
@login_required
def manager_dashboard():
    active_site_id = session.get("active_site_id")

    if not active_site_id:
        return render_template(
            "dashboard/manager.html",
            title="Dashboard Jefatura",
            subtitle="Revise y autorice solicitudes antes de que lleguen a bodega.",
            pending_requests=[],
            pending_requests_count=0,
            pending_lines_count=0,
        )

    try:
        active_site_id = int(active_site_id)

        pending_requests = (
            WorkOrderRequest.query
            .join(WorkOrder, WorkOrder.id == WorkOrderRequest.work_order_id)
            .filter(
                WorkOrder.site_id == active_site_id,
                WorkOrderRequest.request_status == "ENVIADA",
                WorkOrderRequest.sent_to_warehouse_at.is_(None),
            )
            .order_by(WorkOrderRequest.created_at.desc())
            .all()
        )

        pending_requests_count = len(pending_requests)
        pending_lines_count = 0

        for req in pending_requests:
            req.work_order_number = req.work_order.number if req.work_order else "-"
            req.equipment_code_snapshot = (
                req.work_order.equipment_code_snapshot if req.work_order else "-"
            )
            req.requested_by_name = (
                req.requested_by_user.full_name if req.requested_by_user else "-"
            )

            lines = req.lines

            req.visible_lines = []
            has_approved_lines = False
            all_lines_decided = True

            for line in lines:
                # 🔥 CAMBIO REAL AQUÍ
                if line.manager_review_status == "RECHAZADA":
                    line.manager_decision = "RECHAZADA"

                elif line.manager_review_status == "APROBADA":
                    line.manager_decision = "APROBADA"
                    has_approved_lines = True

                else:
                    line.manager_decision = "PENDIENTE"
                    all_lines_decided = False

                req.visible_lines.append(line)
                pending_lines_count += 1

            req.send_to_warehouse_enabled = all_lines_decided and has_approved_lines

        return render_template(
            "dashboard/manager.html",
            title="Dashboard Jefatura",
            subtitle="Revise y autorice solicitudes antes de que lleguen a bodega.",
            pending_requests=pending_requests,
            pending_requests_count=pending_requests_count,
            pending_lines_count=pending_lines_count,
        )

    except Exception as exc:
        print(f"[MANAGER DASHBOARD ERROR] {exc}")
        return render_template(
            "dashboard/manager.html",
            title="Dashboard Jefatura",
            subtitle="Revise y autorice solicitudes antes de que lleguen a bodega.",
            pending_requests=[],
            pending_requests_count=0,
            pending_lines_count=0,
        )