from datetime import datetime
import hashlib
from flask import (
    Blueprint,
    abort,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
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

def _get_manager_material_requests(
    active_site_id: int,
) -> dict:
    """
    Carga únicamente las solicitudes de artículos de OT
    pendientes de revisión por Jefatura.

    Características:
    - consulta las solicitudes y relaciones en bloque;
    - consulta el stock en bloque;
    - no modifica objetos de base de datos;
    - devuelve datos serializables para JSON;
    - evita consultas dentro de ciclos.
    """

    active_site_id = int(active_site_id)

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
            )
            .joinedload(
                WorkOrderRequestLine.article
            )
            .joinedload(
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

    stock_keys = set()

    for request_obj in pending_requests:
        work_order = request_obj.work_order

        if not work_order:
            continue

        warehouse_id = work_order.warehouse_id

        if not warehouse_id:
            continue

        for line in request_obj.lines:
            if not line.article_id:
                continue

            stock_keys.add(
                (
                    int(line.article_id),
                    int(warehouse_id),
                )
            )

    stock_map = _stock_available_map(
        stock_keys
    )

    request_items = []
    total_lines = 0

    for request_obj in pending_requests:
        work_order = request_obj.work_order
        mechanic = request_obj.mechanic

        warehouse_id = (
            work_order.warehouse_id
            if work_order
            else None
        )

        line_items = []

        approved_count = 0
        rejected_count = 0
        pending_count = 0

        for line in request_obj.lines:
            article = line.article
            unit = (
                article.unit
                if article
                else None
            )

            review_status = (
                line.manager_review_status
                or "PENDIENTE"
            ).strip().upper()

            if review_status == "APROBADA":
                approved_count += 1

            elif review_status == "RECHAZADA":
                rejected_count += 1

            else:
                review_status = "PENDIENTE"
                pending_count += 1

            stock_available = 0

            if line.article_id and warehouse_id:
                stock_available = (
                    stock_map.get(
                        (
                            int(line.article_id),
                            int(warehouse_id),
                        ),
                        0,
                    )
                    or 0
                )

            quantity_requested = (
                line.quantity_requested
                or 0
            )

            quantity_text = format(
                quantity_requested,
                "f",
            )

            if "." in quantity_text:
                quantity_text = (
                    quantity_text
                    .rstrip("0")
                    .rstrip(".")
                )

            stock_text = format(
                stock_available,
                "f",
            )

            if "." in stock_text:
                stock_text = (
                    stock_text
                    .rstrip("0")
                    .rstrip(".")
                )

            line_items.append(
                {
                    "id": int(line.id),

                    "article_id": (
                        int(line.article_id)
                        if line.article_id
                        else None
                    ),

                    "article_code": (
                        (
                            article.code
                            or ""
                        ).strip()
                        if article
                        else ""
                    ),

                    "article_name": (
                        (
                            article.name
                            or ""
                        ).strip()
                        if article
                        else "Artículo no disponible"
                    ),

                    "unit_code": (
                        (
                            unit.code
                            or ""
                        ).strip()
                        if unit
                        else ""
                    ),

                    "quantity_requested": (
                        quantity_text
                    ),

                    "quantity_attended": str(
                        line.quantity_attended
                        or 0
                    ),

                    "stock_available": (
                        stock_text
                    ),

                    "manager_decision": (
                        review_status
                    ),

                    "notes": (
                        line.notes
                        or ""
                    ),

                    "rejection_reason": (
                        line.not_delivered_reason
                        or ""
                    ),

                    "line_status": (
                        line.line_status
                        or ""
                    ),
                }
            )

        total_lines += len(
            line_items
        )

        request_items.append(
            {
                "id": int(request_obj.id),

                "work_order_id": (
                    int(work_order.id)
                    if work_order
                    else None
                ),

                "work_order_number": (
                    str(work_order.number)
                    if work_order
                    and work_order.number is not None
                    else "-"
                ),

                "equipment": (
                    (
                        work_order
                        .equipment_code_snapshot
                        or ""
                    ).strip()
                    if work_order
                    else ""
                ) or "Sin equipo",

                "warehouse_id": (
                    int(warehouse_id)
                    if warehouse_id
                    else None
                ),

                "mechanic_id": (
                    int(mechanic.id)
                    if mechanic
                    else None
                ),

                "mechanic_name": (
                    (
                        mechanic.name
                        or ""
                    ).strip()
                    if mechanic
                    else "-"
                ),

                "created_at": (
                    request_obj.created_at.isoformat()
                    if request_obj.created_at
                    else None
                ),

                "request_status": (
                    request_obj.request_status
                    or ""
                ),

                "line_count": len(
                    line_items
                ),

                "approved_count": (
                    approved_count
                ),

                "rejected_count": (
                    rejected_count
                ),

                "pending_count": (
                    pending_count
                ),

                "lines": line_items,
            }
        )

    return {
        "requests": request_items,
        "request_count": len(
            request_items
        ),
        "line_count": total_lines,
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


@dashboard_bp.route(
    "/dashboard/jefatura"
)
@login_required
def manager_dashboard():
    active_site_id = session.get(
        "active_site_id"
    )

    if not active_site_id:
        return render_template(
            "dashboard/manager.html",
            **_empty_manager_context(),
        )

    try:
        active_site_id = int(
            active_site_id
        )

        # =====================================================
        # 1. SOLICITUDES OT: SOLO CONTADORES LIVIANOS
        # =====================================================
        #
        # El nuevo manager.html ya no renderiza las solicitudes
        # OT directamente desde Jinja.
        #
        # Las solicitudes completas, sus artículos y el stock se
        # cargan después mediante AJAX usando:
        #
        # /dashboard/jefatura/material-requests/data
        #
        # Aquí solamente calculamos:
        # - cantidad de solicitudes pendientes;
        # - cantidad de líneas dentro de esas solicitudes.
        #
        # Esto evita cargar:
        # - WorkOrderRequest completos;
        # - relaciones de OT;
        # - mecánicos;
        # - artículos;
        # - unidades;
        # - stock por artículo.
        # =====================================================

        pending_request_ids_query = (
            db.session.query(
                WorkOrderRequest.id.label(
                    "request_id"
                )
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
                    ),
                ),

                WorkOrderRequest.request_status
                == "ENVIADA",

                WorkOrderRequest.sent_to_warehouse_at.is_(
                    None
                ),
            )
        )

        pending_request_ids_subquery = (
            pending_request_ids_query
            .subquery()
        )

        pending_requests_count = (
            db.session.query(
                db.func.count()
            )
            .select_from(
                pending_request_ids_subquery
            )
            .scalar()
            or 0
        )

        pending_lines_count = (
            db.session.query(
                db.func.count(
                    WorkOrderRequestLine.id
                )
            )
            .join(
                pending_request_ids_subquery,
                pending_request_ids_subquery
                .c.request_id
                == WorkOrderRequestLine
                .work_order_request_id,
            )
            .scalar()
            or 0
        )

        # El template nuevo ya no utiliza esta lista.
        # Se mantiene vacía para compatibilidad con el contexto.
        pending_requests = []

        # =====================================================
        # 2. SOLICITUDES DE COMPRA
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
                        PurchaseRequest
                        .sent_direct_to_procurement
                        .is_(False),
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

        for purchase_request in purchase_requests:
            warehouse_id = (
                purchase_request.warehouse_id
            )

            if not warehouse_id:
                continue

            for line in purchase_request.lines:
                if line.line_status == "CANCELADA":
                    continue

                if not line.article_id:
                    continue

                purchase_stock_keys.add(
                    (
                        int(line.article_id),
                        int(warehouse_id),
                    )
                )

        purchase_stock_map = (
            _stock_available_map(
                purchase_stock_keys
            )
        )

        purchase_requests_count = len(
            purchase_requests
        )

        purchase_request_lines_count = 0

        for purchase_request in purchase_requests:
            warehouse_id = (
                purchase_request.warehouse_id
            )

            visible_lines = []

            for line in purchase_request.lines:
                if line.line_status == "CANCELADA":
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

                visible_lines.append(
                    line
                )

            purchase_request.visible_lines = (
                visible_lines
            )

            purchase_request_lines_count += len(
                visible_lines
            )

        # =====================================================
        # 3. SOLICITUDES DE TRASLADO
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

        for transfer_request in (
            transfer_pending_requests
        ):
            for line in transfer_request.lines:
                transfer_lines_bulk.append(
                    {
                        "line_id": line.id,
                        "article_id": (
                            line.article_id
                        ),
                        "requesting_warehouse_id": (
                            transfer_request
                            .origin_warehouse_id
                        ),
                        "supplying_warehouse_id": (
                            transfer_request
                            .destination_warehouse_id
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

        for transfer_request in (
            transfer_pending_requests
        ):
            visible_lines = []
            stock_map = {}

            has_approved_lines = False
            all_lines_decided = True

            requested_by_user = (
                transfer_request.requested_by_user
            )

            if requested_by_user:
                transfer_request.requested_by_name = (
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
                transfer_request.requested_by_name = (
                    "-"
                )

            for line in transfer_request.lines:
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

                visible_lines.append(
                    line
                )

            transfer_request.visible_lines = (
                visible_lines
            )

            transfer_request.stock_map = (
                stock_map
            )

            transfer_pending_lines_count += len(
                visible_lines
            )

            transfer_request.finalize_review_enabled = (
                transfer_request.status
                == "ENVIADA"
                and all_lines_decided
            )

            transfer_request.send_to_warehouse_enabled = (
                transfer_request.status
                == "APROBADA"
                and has_approved_lines
            )

        # =====================================================
        # 4. SOLICITUDES DE FINALIZACIÓN DE TRABAJOS
        # =====================================================

        task_finish_requests = (
            WorkOrderTaskLineFinishRequest.query
            .options(
                joinedload(
                    WorkOrderTaskLineFinishRequest
                    .task_line
                ).joinedload(
                    WorkOrderTaskLine.work_order
                ),
                joinedload(
                    WorkOrderTaskLineFinishRequest
                    .task_line
                ).joinedload(
                    WorkOrderTaskLine.repair_type
                ),
                joinedload(
                    WorkOrderTaskLineFinishRequest
                    .requested_by_mechanic
                ),
            )
            .join(
                WorkOrderTaskLine,
                WorkOrderTaskLine.id
                == WorkOrderTaskLineFinishRequest
                .task_line_id,
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
                WorkOrderTaskLineFinishRequest
                .created_at
                .desc(),
                WorkOrderTaskLineFinishRequest
                .id
                .desc(),
            )
            .all()
        )

        task_finish_requests_count = len(
            task_finish_requests
        )

        for task_request in task_finish_requests:
            task_line = (
                task_request.task_line
            )

            seconds = (
                int(
                    task_line.effective_seconds
                    or 0
                )
                if task_line
                else 0
            )

            hours = (
                seconds // 3600
            )

            minutes = (
                seconds % 3600
            ) // 60

            task_request.formatted_time = (
                f"{hours}h {minutes}m"
            )

        # =====================================================
        # 5. RENDER
        # =====================================================

        return render_template(
            "dashboard/manager.html",

            title=(
                "Dashboard Jefatura"
            ),

            subtitle=(
                "Revise y autorice solicitudes "
                "antes de que lleguen a bodega."
            ),

            pending_requests=(
                pending_requests
            ),

            pending_requests_count=(
                int(
                    pending_requests_count
                )
            ),

            pending_lines_count=(
                int(
                    pending_lines_count
                )
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

    except (
        TypeError,
        ValueError,
    ) as exc:
        db.session.rollback()

        print(
            "[MANAGER DASHBOARD INVALID SITE ERROR] "
            f"{type(exc).__name__}: {exc}"
        )

        return render_template(
            "dashboard/manager.html",
            **_empty_manager_context(),
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


@dashboard_bp.route(
    "/dashboard/jefatura/material-requests/data",
    methods=["GET"],
)
@login_required
def manager_material_requests_data():
    """
    Devuelve las solicitudes OT pendientes para el nuevo
    Dashboard Jefatura.

    Este endpoint solo se consulta:
    - al abrir la pantalla;
    - cuando la versión indica que hubo cambios;
    - después de una actualización manual.

    No realiza polling constante sobre stock y relaciones.
    """

    active_site_id = session.get(
        "active_site_id"
    )

    if not active_site_id:
        return jsonify(
            {
                "ok": False,
                "error": (
                    "No hay predio activo seleccionado."
                ),
                "requests": [],
                "request_count": 0,
                "line_count": 0,
            }
        ), 400

    try:
        active_site_id = int(
            active_site_id
        )

        result = (
            _get_manager_material_requests(
                active_site_id
            )
        )

        signature_parts = []

        for request_item in result[
            "requests"
        ]:
            signature_parts.append(
                "|".join(
                    [
                        str(
                            request_item["id"]
                        ),
                        str(
                            request_item[
                                "request_status"
                            ]
                        ),
                        str(
                            request_item[
                                "approved_count"
                            ]
                        ),
                        str(
                            request_item[
                                "rejected_count"
                            ]
                        ),
                        str(
                            request_item[
                                "pending_count"
                            ]
                        ),
                    ]
                )
            )

            for line in request_item[
                "lines"
            ]:
                signature_parts.append(
                    "|".join(
                        [
                            str(line["id"]),
                            str(
                                line[
                                    "manager_decision"
                                ]
                            ),
                            str(
                                line[
                                    "quantity_requested"
                                ]
                            ),
                            str(
                                line[
                                    "stock_available"
                                ]
                            ),
                        ]
                    )
                )

        signature_source = "\n".join(
            signature_parts
        )

        etag_value = hashlib.sha256(
            signature_source.encode(
                "utf-8"
            )
        ).hexdigest()

        client_etag = (
            request.headers.get(
                "If-None-Match"
            )
            or ""
        ).strip().strip('"')

        if client_etag == etag_value:
            response = make_response(
                "",
                304,
            )

            response.set_etag(
                etag_value
            )

            response.headers[
                "Cache-Control"
            ] = "private, no-cache"

            return response

        response = jsonify(
            {
                "ok": True,
                "requests": result[
                    "requests"
                ],
                "request_count": result[
                    "request_count"
                ],
                "line_count": result[
                    "line_count"
                ],
            }
        )

        response.set_etag(
            etag_value
        )

        response.headers[
            "Cache-Control"
        ] = "private, no-cache"

        return response

    except Exception as exc:
        db.session.rollback()

        print(
            "[MANAGER MATERIAL REQUESTS DATA ERROR] "
            f"{type(exc).__name__}: {exc}"
        )

        return jsonify(
            {
                "ok": False,
                "error": (
                    "No fue posible cargar las "
                    "solicitudes de artículos."
                ),
                "requests": [],
                "request_count": 0,
                "line_count": 0,
            }
        ), 500

# =========================================================
# MONITOR DE ARTÍCULOS POR ALISTAR
# =========================================================

WAREHOUSE_MONITOR_ALLOWED_ROLES = {
    "BODEGA",
    "ADMIN",
    "SUPER_USUARIO",
}


def _validate_warehouse_monitor_access() -> int:
    """
    Valida el acceso al monitor y devuelve el predio activo.

    Los equipos y artículos son globales, pero las solicitudes
    mostradas corresponden al predio activo del usuario.
    """

    role_code = (
        current_user.role_code
        or ""
    ).strip().upper()

    if role_code not in WAREHOUSE_MONITOR_ALLOWED_ROLES:
        abort(403)

    active_site_id = session.get(
        "active_site_id"
    )

    if not active_site_id:
        abort(
            400,
            description=(
                "Debe seleccionar un predio activo."
            ),
        )

    try:
        return int(active_site_id)

    except (TypeError, ValueError):
        abort(
            400,
            description=(
                "El predio activo no es válido."
            ),
        )


@dashboard_bp.route(
    "/dashboard/bodega-monitor",
    methods=["GET"],
)
@login_required
def warehouse_preparation_monitor():
    """
    Muestra la pantalla fija de artículos por alistar.
    """

    _validate_warehouse_monitor_access()

    return render_template(
        "dashboard/warehouse_preparation_monitor.html"
    )


@dashboard_bp.route(
    "/dashboard/bodega-monitor/data",
    methods=["GET"],
)
@login_required
def warehouse_preparation_monitor_data():
    """
    Devuelve únicamente las líneas aprobadas y pendientes
    de preparación para el predio activo.

    La consulta:
    - selecciona solo las columnas necesarias;
    - no carga relaciones ORM completas;
    - no calcula stock;
    - no modifica objetos;
    - devuelve 304 si la información no cambió;
    - incluye OT/EQUIPO en formato 345/40231.
    """

    active_site_id = (
        _validate_warehouse_monitor_access()
    )

    try:
        pending_quantity_expression = (
            WorkOrderRequestLine.quantity_requested
            - WorkOrderRequestLine.quantity_attended
        )

        rows = (
            db.session.query(
                WorkOrderRequestLine.id.label(
                    "line_id"
                ),
                WorkOrderRequest.id.label(
                    "request_id"
                ),
                WorkOrder.number.label(
                    "work_order_number"
                ),
                WorkOrder.equipment_code_snapshot.label(
                    "equipment_code"
                ),
                Article.code.label(
                    "article_code"
                ),
                Article.name.label(
                    "article_name"
                ),
                pending_quantity_expression.label(
                    "pending_quantity"
                ),
            )
            .join(
                WorkOrderRequest,
                WorkOrderRequest.id
                == WorkOrderRequestLine.work_order_request_id,
            )
            .join(
                WorkOrder,
                WorkOrder.id
                == WorkOrderRequest.work_order_id,
            )
            .join(
                Article,
                Article.id
                == WorkOrderRequestLine.article_id,
            )
            .filter(
                WorkOrder.site_id
                == active_site_id,

                WorkOrderRequest.request_status
                == "ENVIADA",

                WorkOrderRequest.sent_to_warehouse_at.isnot(
                    None
                ),

                WorkOrderRequestLine.manager_review_status
                == "APROBADA",

                WorkOrderRequestLine.line_status.in_(
                    [
                        "SOLICITADA",
                        "ATENDIDA_PARCIAL",
                    ]
                ),

                pending_quantity_expression > 0,
            )
            .order_by(
                WorkOrderRequest.sent_to_warehouse_at.asc(),
                WorkOrderRequest.id.asc(),
                WorkOrderRequestLine.id.asc(),
            )
            .all()
        )

        items = []
        signature_parts = []

        for row in rows:
            pending_quantity = (
                row.pending_quantity or 0
            )

            pending_text = format(
                pending_quantity,
                "f",
            )

            if "." in pending_text:
                pending_text = pending_text.rstrip(
                    "0"
                ).rstrip(".")

            work_order_number = (
                str(row.work_order_number).strip()
                if row.work_order_number is not None
                else "-"
            )

            equipment_code = (
                str(row.equipment_code).strip()
                if row.equipment_code
                else "SIN EQUIPO"
            )

            ot_equipo = (
                f"{work_order_number}/{equipment_code}"
            )

            item = {
                "line_id": int(row.line_id),
                "request_id": int(row.request_id),
                "ot_equipo": ot_equipo,
                "code": (
                    row.article_code
                    or ""
                ).strip(),
                "name": (
                    row.article_name
                    or ""
                ).strip(),
                "quantity": pending_text,
            }

            items.append(item)

            signature_parts.append(
                "|".join(
                    [
                        str(item["line_id"]),
                        str(item["request_id"]),
                        item["ot_equipo"],
                        item["code"],
                        item["name"],
                        item["quantity"],
                    ]
                )
            )

        signature_source = "\n".join(
            signature_parts
        )

        etag_value = hashlib.sha256(
            signature_source.encode("utf-8")
        ).hexdigest()

        client_etag = (
            request.headers.get("If-None-Match")
            or ""
        ).strip().strip('"')

        if client_etag == etag_value:
            response = make_response(
                "",
                304,
            )

            response.set_etag(
                etag_value
            )

            response.headers[
                "Cache-Control"
            ] = "private, no-cache"

            return response

        response = jsonify(
            {
                "ok": True,
                "count": len(items),
                "items": items,
            }
        )

        response.set_etag(
            etag_value
        )

        response.headers[
            "Cache-Control"
        ] = "private, no-cache"

        return response

    except Exception as exc:
        db.session.rollback()

        print(
            "[WAREHOUSE MONITOR ERROR] "
            f"{type(exc).__name__}: {exc}"
        )

        return jsonify(
            {
                "ok": False,
                "message": (
                    "No fue posible cargar los "
                    "artículos pendientes."
                ),
                "items": [],
            }
        ), 500


@dashboard_bp.route(
    "/dashboard/jefatura/material-requests/version",
    methods=["GET"],
)
@login_required
def manager_material_requests_version():
    """
    Endpoint liviano para detectar solicitudes nuevas o retiradas.

    Solo consulta:
    - ID de la solicitud;
    - fecha de actualización;
    - cantidad de líneas.

    No consulta stock ni carga relaciones ORM.
    """

    active_site_id = session.get(
        "active_site_id"
    )

    if not active_site_id:
        return jsonify(
            {
                "ok": False,
                "error": (
                    "No hay predio activo seleccionado."
                ),
            }
        ), 400

    try:
        active_site_id = int(
            active_site_id
        )

        rows = (
            db.session.query(
                WorkOrderRequest.id.label(
                    "request_id"
                ),
                WorkOrderRequest.updated_at.label(
                    "updated_at"
                ),
                db.func.count(
                    WorkOrderRequestLine.id
                ).label(
                    "line_count"
                ),
            )
            .join(
                WorkOrder,
                WorkOrder.id
                == WorkOrderRequest.work_order_id,
            )
            .outerjoin(
                WorkOrderRequestLine,
                WorkOrderRequestLine
                .work_order_request_id
                == WorkOrderRequest.id,
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
                        WorkOrderRequest
                        .sent_to_warehouse_at
                        .is_(None),
                    ),
                ),
                WorkOrderRequest.request_status
                == "ENVIADA",
                WorkOrderRequest.sent_to_warehouse_at
                .is_(None),
            )
            .group_by(
                WorkOrderRequest.id,
                WorkOrderRequest.updated_at,
            )
            .order_by(
                WorkOrderRequest.id.asc(),
            )
            .all()
        )

        signature_parts = []

        total_lines = 0

        for row in rows:
            line_count = int(
                row.line_count or 0
            )

            total_lines += line_count

            updated_text = (
                row.updated_at.isoformat()
                if row.updated_at
                else ""
            )

            signature_parts.append(
                "|".join(
                    [
                        str(row.request_id),
                        updated_text,
                        str(line_count),
                    ]
                )
            )

        signature_source = "\n".join(
            signature_parts
        )

        version = hashlib.sha256(
            signature_source.encode(
                "utf-8"
            )
        ).hexdigest()

        client_etag = (
            request.headers.get(
                "If-None-Match"
            )
            or ""
        ).strip().strip('"')

        if client_etag == version:
            response = make_response(
                "",
                304,
            )

            response.set_etag(
                version
            )

            response.headers[
                "Cache-Control"
            ] = "private, no-cache"

            return response

        response = jsonify(
            {
                "ok": True,
                "version": version,
                "request_count": len(
                    rows
                ),
                "line_count": total_lines,
            }
        )

        response.set_etag(
            version
        )

        response.headers[
            "Cache-Control"
        ] = "private, no-cache"

        return response

    except Exception as exc:
        db.session.rollback()

        print(
            "[MANAGER MATERIAL REQUESTS VERSION ERROR] "
            f"{type(exc).__name__}: {exc}"
        )

        return jsonify(
            {
                "ok": False,
                "error": (
                    "No fue posible verificar "
                    "las solicitudes nuevas."
                ),
            }
        ), 500