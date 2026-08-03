from datetime import datetime

from flask import Blueprint, abort, redirect, render_template, session, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models.inventory import WarehouseStock
from app.models.purchase_request import PurchaseRequest
from app.models.transfer_request import TransferRequest
from app.models.warehouse import Warehouse
from app.models.waste_act import WasteAct
from app.models.work_order import WorkOrder
from app.models.work_order_request import WorkOrderRequest
from app.models.work_order_task_line import WorkOrderTaskLine
from app.models.work_order_task_line_finish_request import WorkOrderTaskLineFinishRequest
from app.services.transfer_service import get_request_line_stock_context
from app.services.transfer_service import get_request_lines_stock_context_bulk
from app.models.purchase_request_line import PurchaseRequestLine
from app.models.purchase_request_line import PurchaseRequestLine
from app.models.transfer_request_line import TransferRequestLine
from app.models.work_order_request_line import WorkOrderRequestLine
from app.models.article import Article


dashboard_bp = Blueprint("dashboard", __name__)


def _empty_dashboard_context(current_time=None):
    return {
        "title": "Dashboard",
        "subtitle": "Vista general del sistema y accesos rápidos.",
        "work_orders_in_process": 0,
        "work_orders_finalized": 0,
        "work_orders_closed": 0,
        "waste_borrador": 0,
        "waste_registrada": 0,
        "waste_impresa": 0,
        "waste_cerrada": 0,
        "waste_cancelada": 0,
        "inventory_records": 0,
        "work_orders_in_process_list": [],
        "current_time": current_time or datetime.now(),
    }


def _empty_manager_context():
    return {
        "title": "Dashboard Jefatura",
        "subtitle": "Revise y autorice solicitudes antes de que lleguen a bodega.",
        "pending_requests": [],
        "pending_requests_count": 0,
        "pending_lines_count": 0,
        "transfer_pending_requests": [],
        "transfer_pending_requests_count": 0,
        "transfer_pending_lines_count": 0,
        "task_finish_requests": [],
        "task_finish_requests_count": 0,
        "purchase_requests": [],
        "purchase_requests_count": 0,
        "purchase_request_lines_count": 0,
    }


def _stock_available_map(stock_keys):
    """
    Recibe pares:
        (article_id, warehouse_id)

    Devuelve:
        {
            (article_id, warehouse_id): available_quantity
        }

    Evita consultar WarehouseStock individualmente por cada línea.
    """
    clean_keys = {
        (int(article_id), int(warehouse_id))
        for article_id, warehouse_id in stock_keys
        if article_id and warehouse_id
    }

    if not clean_keys:
        return {}

    article_ids = {
        article_id
        for article_id, _ in clean_keys
    }

    warehouse_ids = {
        warehouse_id
        for _, warehouse_id in clean_keys
    }

    rows = (
        WarehouseStock.query
        .filter(
            WarehouseStock.article_id.in_(article_ids),
            WarehouseStock.warehouse_id.in_(warehouse_ids),
        )
        .all()
    )

    return {
        (int(row.article_id), int(row.warehouse_id)): (
            row.available_quantity or 0
        )
        for row in rows
        if (int(row.article_id), int(row.warehouse_id)) in clean_keys
    }


def _apply_work_order_semaphore(work_orders):
    """
    Mantiene exactamente la lógica visual actual del semáforo.
    Solo se centraliza para no duplicar código entre dashboard normal y parcial.
    """
    for ot in work_orders:
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

            for line in req.lines:
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

    return work_orders


@dashboard_bp.route("/")
def home():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login_page"))

    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/set-site/<int:site_id>")
@login_required
def set_site(site_id):
    if not current_user.can_access_site(site_id):
        abort(403)

    session["active_site_id"] = site_id

    return redirect(url_for("home.index"))


@dashboard_bp.route("/dashboard")
@login_required
def index():
    active_site_id = session.get("active_site_id")
    current_time = datetime.now()

    if not active_site_id:
        return render_template(
            "dashboard/index.html",
            **_empty_dashboard_context(current_time),
        )

    try:
        active_site_id = int(active_site_id)

        work_order_status_rows = (
            db.session.query(
                WorkOrder.status,
                db.func.count(WorkOrder.id),
            )
            .filter(WorkOrder.site_id == active_site_id)
            .group_by(WorkOrder.status)
            .all()
        )

        work_order_counts = {
            status: count
            for status, count in work_order_status_rows
        }

        waste_status_rows = (
            db.session.query(
                WasteAct.status,
                db.func.count(WasteAct.id),
            )
            .filter(WasteAct.site_id == active_site_id)
            .group_by(WasteAct.status)
            .all()
        )

        waste_counts = {
            status: count
            for status, count in waste_status_rows
        }

        inventory_records = (
            WarehouseStock.query
            .join(Warehouse, Warehouse.id == WarehouseStock.warehouse_id)
            .filter(Warehouse.site_id == active_site_id)
            .count()
        )

        # IMPORTANTE:
        # Ya NO cargamos aquí la lista de OTs en proceso.
        # Esa lista es pesada porque carga requests, líneas y herramientas.
        # Se cargará después por AJAX usando:
        # /dashboard/partial/work-orders
        return render_template(
            "dashboard/index.html",
            title="Dashboard",
            subtitle="Vista general del sistema y accesos rápidos.",
            work_orders_in_process=work_order_counts.get("EN_PROCESO", 0),
            work_orders_finalized=work_order_counts.get("FINALIZADA", 0),
            work_orders_closed=work_order_counts.get("CERRADA", 0),
            waste_borrador=waste_counts.get("BORRADOR", 0),
            waste_registrada=waste_counts.get("REGISTRADA", 0),
            waste_impresa=waste_counts.get("IMPRESA", 0),
            waste_cerrada=waste_counts.get("CERRADA", 0),
            waste_cancelada=waste_counts.get("CANCELADA", 0),
            inventory_records=inventory_records,
            work_orders_in_process_list=[],
            current_time=current_time,
        )

    except Exception as exc:
        print(f"[DASHBOARD ERROR] {exc}")
        return render_template(
            "dashboard/index.html",
            **_empty_dashboard_context(current_time),
        )


@dashboard_bp.route("/dashboard/partial/work-orders")
@login_required
def dashboard_work_orders_partial():
    active_site_id = session.get("active_site_id")

    if not active_site_id:
        return ""

    try:
        active_site_id = int(active_site_id)

        work_orders = (
            WorkOrder.query
            .options(
                selectinload(WorkOrder.requests).selectinload(WorkOrderRequest.lines),
                selectinload(WorkOrder.tool_loans),
            )
            .filter(
                WorkOrder.site_id == active_site_id,
                WorkOrder.status == "EN_PROCESO",
            )
            .order_by(WorkOrder.created_at.desc())
            .all()
        )

        _apply_work_order_semaphore(work_orders)

        return render_template(
            "dashboard/_work_orders.html",
            work_orders_in_process_list=work_orders,
        )

    except Exception as exc:
        print(f"[DASHBOARD PARTIAL WORK ORDERS ERROR] {exc}")
        return ""


@dashboard_bp.route("/dashboard/jefatura")
@login_required
def manager_dashboard():
    active_site_id = session.get("active_site_id")

    if not active_site_id:
        return render_template(
            "dashboard/manager.html",
            **_empty_manager_context(),
        )

    try:
        active_site_id = int(active_site_id)

        # =====================================================
        # 1. SOLICITUDES DE MATERIALES DE ÓRDENES DE TRABAJO
        # =====================================================
        #
        # Se precargan:
        # - OT asociada.
        # - Mecánico solicitante.
        # - Líneas.
        # - Artículo de cada línea.
        # - Unidad del artículo.
        #
        # Esto evita consultas adicionales desde el template al usar:
        # line.article.code
        # line.article.name
        # line.article.unit
        # =====================================================

        pending_requests = (
            WorkOrderRequest.query
            .options(
                joinedload(
                    WorkOrderRequest.work_order
                ),
                joinedload(
                    WorkOrderRequest.mechanic
                ),
                selectinload(
                    WorkOrderRequest.lines
                ).joinedload(
                    WorkOrderRequestLine.article
                ).joinedload(
                    Article.unit
                ),
            )
            .join(
                WorkOrder,
                WorkOrder.id
                == WorkOrderRequest.work_order_id,
            )
            .filter(
                db.or_(
                    WorkOrderRequest.review_site_id
                    == active_site_id,
                    db.and_(
                        WorkOrderRequest.review_site_id.is_(
                            None
                        ),
                        WorkOrder.site_id
                        == active_site_id,
                        WorkOrderRequest.sent_to_warehouse_at.is_(
                            None
                        ),
                    ),
                ),
                WorkOrderRequest.request_status
                == "ENVIADA",
                WorkOrderRequest.sent_to_warehouse_at.is_(
                    None
                ),
            )
            .order_by(
                WorkOrderRequest.created_at.desc(),
                WorkOrderRequest.id.desc(),
            )
            .all()
        )

        pending_stock_keys: set[
            tuple[int, int]
        ] = set()

        for req in pending_requests:
            work_order = req.work_order

            if not work_order:
                continue

            warehouse_id = work_order.warehouse_id

            if not warehouse_id:
                continue

            for line in req.lines:
                if not line.article_id:
                    continue

                pending_stock_keys.add(
                    (
                        int(line.article_id),
                        int(warehouse_id),
                    )
                )

        pending_stock_map = _stock_available_map(
            pending_stock_keys
        )

        pending_requests_count = len(
            pending_requests
        )

        pending_lines_count = 0

        for req in pending_requests:
            work_order = req.work_order

            req.work_order_number = (
                work_order.number
                if work_order
                else "-"
            )

            req.equipment_code_snapshot = (
                work_order.equipment_code_snapshot
                if work_order
                else "-"
            )

            req.requested_by_name = (
                req.mechanic.name
                if req.mechanic
                else "-"
            )

            warehouse_id = (
                work_order.warehouse_id
                if work_order
                else None
            )

            visible_lines = []
            has_approved_lines = False
            all_lines_decided = True

            for line in req.lines:
                stock_key = (
                    line.article_id,
                    warehouse_id,
                )

                line.stock_available = (
                    pending_stock_map.get(
                        stock_key,
                        0,
                    )
                    if (
                        line.article_id
                        and warehouse_id
                    )
                    else 0
                )

                review_status = (
                    line.manager_review_status
                    or "PENDIENTE"
                )

                if review_status == "RECHAZADA":
                    line.manager_decision = (
                        "RECHAZADA"
                    )

                elif review_status == "APROBADA":
                    line.manager_decision = (
                        "APROBADA"
                    )
                    has_approved_lines = True

                else:
                    line.manager_decision = (
                        "PENDIENTE"
                    )
                    all_lines_decided = False

                visible_lines.append(line)

            req.visible_lines = visible_lines

            pending_lines_count += len(
                visible_lines
            )

            req.send_to_warehouse_enabled = (
                all_lines_decided
                and has_approved_lines
            )

        # =====================================================
        # 2. SOLICITUDES DE COMPRA
        # =====================================================
        #
        # Antes solo se precargaban las líneas. El template usa:
        # - req.site
        # - req.warehouse
        # - line.article
        # - line.pending_article
        # - line.unit
        # - line.item_code
        # - line.item_name
        #
        # Todas esas relaciones quedan cargadas de antemano.
        # =====================================================

        purchase_requests = (
            PurchaseRequest.query
            .options(
                joinedload(
                    PurchaseRequest.requested_by_user
                ),
                joinedload(
                    PurchaseRequest.site
                ),
                joinedload(
                    PurchaseRequest.warehouse
                ),
                selectinload(
                    PurchaseRequest.lines
                ).joinedload(
                    PurchaseRequestLine.article
                ),
                selectinload(
                    PurchaseRequest.lines
                ).joinedload(
                    PurchaseRequestLine.pending_article
                ),
                selectinload(
                    PurchaseRequest.lines
                ).joinedload(
                    PurchaseRequestLine.unit
                ),
            )
            .filter(
                db.or_(
                    PurchaseRequest.review_site_id
                    == active_site_id,
                    db.and_(
                        PurchaseRequest.review_site_id.is_(
                            None
                        ),
                        PurchaseRequest.site_id
                        == active_site_id,
                        PurchaseRequest.sent_direct_to_procurement.is_(
                            False
                        ),
                    ),
                ),
                PurchaseRequest.status
                == "ENVIADA",
            )
            .order_by(
                PurchaseRequest.created_at.desc(),
                PurchaseRequest.id.desc(),
            )
            .all()
        )

        purchase_stock_keys: set[
            tuple[int, int]
        ] = set()

        for req in purchase_requests:
            warehouse_id = req.warehouse_id

            if not warehouse_id:
                continue

            for line in req.lines:
                if (
                    line.line_status
                    == "CANCELADA"
                ):
                    continue

                if not line.article_id:
                    continue

                purchase_stock_keys.add(
                    (
                        int(line.article_id),
                        int(warehouse_id),
                    )
                )

        purchase_stock_map = _stock_available_map(
            purchase_stock_keys
        )

        purchase_requests_count = len(
            purchase_requests
        )

        purchase_request_lines_count = 0

        for req in purchase_requests:
            warehouse_id = req.warehouse_id
            visible_lines = []

            for line in req.lines:
                if (
                    line.line_status
                    == "CANCELADA"
                ):
                    continue

                stock_key = (
                    line.article_id,
                    warehouse_id,
                )

                line.stock_available = (
                    purchase_stock_map.get(
                        stock_key,
                        0,
                    )
                    if (
                        line.article_id
                        and warehouse_id
                    )
                    else 0
                )

                visible_lines.append(line)

            req.visible_lines = visible_lines

            purchase_request_lines_count += len(
                visible_lines
            )

        # =====================================================
        # 3. SOLICITUDES DE TRASLADO
        # =====================================================
        #
        # El template utiliza:
        # - req.requested_by_user
        # - req.origin_warehouse
        # - req.destination_warehouse
        # - line.article
        # - line.article.unit
        #
        # Estas relaciones se precargan para evitar consultas por línea.
        # =====================================================

        transfer_pending_requests = (
            TransferRequest.query
            .options(
                joinedload(
                    TransferRequest.requested_by_user
                ),
                joinedload(
                    TransferRequest.origin_warehouse
                ),
                joinedload(
                    TransferRequest.destination_warehouse
                ),
                selectinload(
                    TransferRequest.lines
                ).joinedload(
                    TransferRequestLine.article
                ).joinedload(
                    Article.unit
                ),
            )
            .filter(
                db.or_(
                    TransferRequest.review_site_id
                    == active_site_id,
                    db.and_(
                        TransferRequest.review_site_id.is_(
                            None
                        ),
                        TransferRequest.destination_site_id
                        == active_site_id,
                    ),
                ),
                TransferRequest.status.in_(
                    [
                        "ENVIADA",
                        "APROBADA",
                    ]
                ),
                TransferRequest.sent_to_warehouse_at.is_(
                    None
                ),
            )
            .order_by(
                TransferRequest.created_at.desc(),
                TransferRequest.id.desc(),
            )
            .all()
        )

        transfer_lines_bulk = []

        for req in transfer_pending_requests:
            for line in req.lines:
                transfer_lines_bulk.append(
                    {
                        "line_id": line.id,
                        "article_id": (
                            line.article_id
                        ),
                        "requesting_warehouse_id": (
                            req.origin_warehouse_id
                        ),
                        "supplying_warehouse_id": (
                            req.destination_warehouse_id
                        ),
                    }
                )

        bulk_transfer_stock_map = (
            get_request_lines_stock_context_bulk(
                transfer_lines_bulk
            )
            if transfer_lines_bulk
            else {}
        )

        transfer_pending_requests_count = len(
            transfer_pending_requests
        )

        transfer_pending_lines_count = 0

        for req in transfer_pending_requests:
            visible_lines = []
            stock_map = {}

            has_approved_lines = False
            all_lines_decided = True

            requested_by_user = (
                req.requested_by_user
            )

            if requested_by_user:
                req.requested_by_name = (
                    getattr(
                        requested_by_user,
                        "full_name",
                        None,
                    )
                    or getattr(
                        requested_by_user,
                        "username",
                        None,
                    )
                    or "-"
                )
            else:
                req.requested_by_name = "-"

            for line in req.lines:
                review_status = (
                    line.manager_review_status
                    or "PENDIENTE"
                )

                if review_status == "RECHAZADA":
                    line.manager_decision = (
                        "RECHAZADA"
                    )

                elif review_status == "APROBADA":
                    line.manager_decision = (
                        "APROBADA"
                    )
                    has_approved_lines = True

                else:
                    line.manager_decision = (
                        "PENDIENTE"
                    )
                    all_lines_decided = False

                stock_map[line.id] = (
                    bulk_transfer_stock_map.get(
                        line.id,
                        {
                            "requesting_available_quantity": 0,
                            "supplying_available_quantity": 0,
                        },
                    )
                )

                visible_lines.append(line)

            req.visible_lines = visible_lines
            req.stock_map = stock_map

            transfer_pending_lines_count += len(
                visible_lines
            )

            req.finalize_review_enabled = (
                req.status == "ENVIADA"
                and all_lines_decided
            )

            req.send_to_warehouse_enabled = (
                req.status == "APROBADA"
                and has_approved_lines
            )

        # =====================================================
        # 4. SOLICITUDES DE FINALIZACIÓN DE TRABAJOS
        # =====================================================
        #
        # El template utiliza:
        # - task_line.work_order
        # - task_line.repair_type
        # - requested_by_mechanic
        #
        # Se cargan antes del render para eliminar consultas N+1.
        # =====================================================

        task_finish_requests = (
            WorkOrderTaskLineFinishRequest.query
            .options(
                joinedload(
                    WorkOrderTaskLineFinishRequest.task_line
                ).joinedload(
                    WorkOrderTaskLine.work_order
                ),
                joinedload(
                    WorkOrderTaskLineFinishRequest.task_line
                ).joinedload(
                    WorkOrderTaskLine.repair_type
                ),
                joinedload(
                    WorkOrderTaskLineFinishRequest.requested_by_mechanic
                ),
            )
            .join(
                WorkOrderTaskLine,
                WorkOrderTaskLine.id
                == WorkOrderTaskLineFinishRequest.task_line_id,
            )
            .join(
                WorkOrder,
                WorkOrder.id
                == WorkOrderTaskLine.work_order_id,
            )
            .filter(
                WorkOrder.site_id
                == active_site_id,
                WorkOrderTaskLineFinishRequest.status
                == "PENDIENTE",
            )
            .order_by(
                WorkOrderTaskLineFinishRequest.created_at.desc(),
                WorkOrderTaskLineFinishRequest.id.desc(),
            )
            .all()
        )

        task_finish_requests_count = len(
            task_finish_requests
        )

        for task_req in task_finish_requests:
            task_line = task_req.task_line

            seconds = (
                int(
                    task_line.effective_seconds
                    or 0
                )
                if task_line
                else 0
            )

            hours = seconds // 3600
            minutes = (
                seconds % 3600
            ) // 60

            task_req.formatted_time = (
                f"{hours}h {minutes}m"
            )

        # =====================================================
        # 5. RENDER
        # =====================================================

        return render_template(
            "dashboard/manager.html",
            title="Dashboard Jefatura",
            subtitle=(
                "Revise y autorice solicitudes "
                "antes de que lleguen a bodega."
            ),
            pending_requests=(
                pending_requests
            ),
            pending_requests_count=(
                pending_requests_count
            ),
            pending_lines_count=(
                pending_lines_count
            ),
            transfer_pending_requests=(
                transfer_pending_requests
            ),
            transfer_pending_requests_count=(
                transfer_pending_requests_count
            ),
            transfer_pending_lines_count=(
                transfer_pending_lines_count
            ),
            task_finish_requests=(
                task_finish_requests
            ),
            task_finish_requests_count=(
                task_finish_requests_count
            ),
            purchase_requests=(
                purchase_requests
            ),
            purchase_requests_count=(
                purchase_requests_count
            ),
            purchase_request_lines_count=(
                purchase_request_lines_count
            ),
        )

    except Exception as exc:
        db.session.rollback()

        print(
            "[MANAGER DASHBOARD ERROR] "
            f"{type(exc).__name__}: {exc}"
        )

        return render_template(
            "dashboard/manager.html",
            **_empty_manager_context(),
        )