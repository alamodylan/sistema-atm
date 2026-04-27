from datetime import UTC, datetime

from flask import Blueprint, render_template, request, jsonify, session
from flask_login import login_required, current_user

from app.extensions import db
from app.models.mechanic import Mechanic
from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLine
from app.models.work_order_request import WorkOrderRequest
from app.models.tool_loan import ToolLoan
from app.models.work_order_request_line import WorkOrderRequestLine
from app.models.work_order_task_line import WorkOrderTaskLine
from app.models.work_order_task_line_assignment import WorkOrderTaskLineAssignment
from app.models.work_order_task_line_finish_request import WorkOrderTaskLineFinishRequest
from app.services.work_order_request_service import confirm_request_line_to_work_order
from app.services.inventory_service import get_inventory_by_warehouse, InventoryServiceError
from app.services.work_order_request_service import (
    WorkOrderRequestServiceError,
    create_request,
    add_request_line,
    send_request,
)

terminal_bp = Blueprint("mechanic_terminal", __name__, url_prefix="/terminal")


@terminal_bp.route("/")
@login_required
def index():
    return render_template("mechanic_terminal/index.html")


@terminal_bp.route("/scan", methods=["POST"])
@login_required
def scan():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    active_site_id = session.get("active_site_id")

    if not code:
        return jsonify({"error": "Código de mecánico requerido"}), 400

    if not active_site_id:
        return jsonify({"error": "No hay predio activo seleccionado"}), 400

    mechanic = Mechanic.query.filter_by(
        code=code,
        site_id=active_site_id,
        is_active=True,
    ).first()

    if not mechanic:
        return jsonify({"error": "Mecánico no encontrado"}), 404

    task_lines = (
        WorkOrderTaskLine.query
        .join(WorkOrder, WorkOrder.id == WorkOrderTaskLine.work_order_id)
        .filter(
            WorkOrderTaskLine.assigned_mechanic_id == mechanic.id,
            WorkOrder.site_id == active_site_id,
            WorkOrder.status == "EN_PROCESO",
            WorkOrderTaskLine.status.in_(
                [
                    "EN_PROCESO",
                    "PAUSADA",
                    "FINALIZACION_SOLICITADA",
                ]
            ),
        )
        .all()
    )

    work_orders_map = {}

    for task_line in task_lines:
        work_order = task_line.work_order

        if not work_order:
            continue

        if work_order.id not in work_orders_map:
            work_orders_map[work_order.id] = {
                "id": work_order.id,
                "number": work_order.number,
                "warehouse_id": work_order.warehouse_id,
                "equipment_code_snapshot": work_order.equipment_code_snapshot,
            }

    work_orders = list(work_orders_map.values())

    return jsonify({
        "mechanic_id": mechanic.id,
        "mechanic": mechanic.name,
        "code": mechanic.code,
        "work_orders": work_orders,
    })


@terminal_bp.route("/articles/<int:warehouse_id>")
@login_required
def get_articles(warehouse_id):
    try:
        items = get_inventory_by_warehouse(warehouse_id)

        filtered = [
            {
                "article_id": i["article_id"],
                "code": i["code"],
                "name": i["name"],
            }
            for i in items
            if float(i["quantity_on_hand"]) > 0
            and i["code"] != "19000"
        ]

        return jsonify({"items": filtered})

    except InventoryServiceError as exc:
        return jsonify({"error": str(exc)}), 400


@terminal_bp.route("/tools/<int:warehouse_id>")
@login_required
def get_tools(warehouse_id):
    try:
        items = get_inventory_by_warehouse(warehouse_id)

        tools = [
            {
                "article_id": i["article_id"],
                "code": i["code"],
                "name": i["name"],
            }
            for i in items
            if float(i["quantity_on_hand"]) > 0
            and i["code"] == "19000"
        ]

        return jsonify({"items": tools})

    except InventoryServiceError as exc:
        return jsonify({"error": str(exc)}), 400


@terminal_bp.route("/borrowed-tools/<int:work_order_id>")
@login_required
def get_borrowed_tools(work_order_id):
    active_site_id = session.get("active_site_id")

    if not active_site_id:
        return jsonify({"error": "No hay predio activo seleccionado"}), 400

    work_order = WorkOrder.query.filter_by(
        id=work_order_id,
        site_id=active_site_id,
    ).first()

    if not work_order:
        return jsonify({"error": "OT no encontrada"}), 404

    loans = (
        ToolLoan.query
        .filter_by(
            work_order_id=work_order_id,
            loan_status="PRESTADA",
        )
        .all()
    )

    items = [
        {
            "tool_loan_id": loan.id,
            "article_id": loan.article_id,
            "code": loan.article.code if loan.article else "",
            "name": loan.article.name if loan.article else "",
            "quantity": str(loan.quantity),
            "loaned_at": loan.loaned_at.isoformat() if loan.loaned_at else None,
        }
        for loan in loans
    ]

    return jsonify({"items": items})


@terminal_bp.route("/work-order/<int:work_order_id>/tasks/<int:mechanic_id>")
@login_required
def get_my_tasks(work_order_id, mechanic_id):
    active_site_id = session.get("active_site_id")

    if not active_site_id:
        return jsonify({"error": "No hay predio activo seleccionado"}), 400

    mechanic = Mechanic.query.filter_by(
        id=mechanic_id,
        site_id=active_site_id,
        is_active=True,
    ).first()

    if not mechanic:
        return jsonify({"error": "Mecánico no encontrado"}), 404

    work_order = WorkOrder.query.filter_by(
        id=work_order_id,
        site_id=active_site_id,
    ).first()

    if not work_order:
        return jsonify({"error": "OT no encontrada"}), 404

    task_lines = (
        WorkOrderTaskLine.query
        .filter(
            WorkOrderTaskLine.work_order_id == work_order.id,
            WorkOrderTaskLine.assigned_mechanic_id == mechanic.id,
        )
        .order_by(WorkOrderTaskLine.created_at.asc())
        .all()
    )

    items = []

    for task_line in task_lines:
        items.append({
            "task_id": task_line.id,
            "title": task_line.title,
            "description": task_line.description,
            "status": task_line.status,
            "repair_type": task_line.repair_type.name if task_line.repair_type else "",
            "started_at": task_line.started_at.isoformat() if task_line.started_at else None,
            "finish_requested_at": task_line.finish_requested_at.isoformat() if task_line.finish_requested_at else None,
            "approved_finished_at": task_line.approved_finished_at.isoformat() if task_line.approved_finished_at else None,
            "effective_seconds": task_line.effective_seconds or 0,
        })

    return jsonify({"items": items})


@terminal_bp.route("/tasks/<int:task_id>/request-finish", methods=["POST"])
@login_required
def request_finish_task(task_id):
    data = request.get_json(silent=True) or {}
    mechanic_id = data.get("mechanic_id")
    active_site_id = session.get("active_site_id")

    if not active_site_id:
        return jsonify({"error": "No hay predio activo seleccionado"}), 400

    if not mechanic_id:
        return jsonify({"error": "Falta el mecánico que realizó el escaneo"}), 400

    mechanic = Mechanic.query.filter_by(
        id=int(mechanic_id),
        site_id=active_site_id,
        is_active=True,
    ).first()

    if not mechanic:
        return jsonify({"error": "Mecánico no encontrado"}), 404

    task_line = (
        WorkOrderTaskLine.query
        .join(WorkOrder, WorkOrder.id == WorkOrderTaskLine.work_order_id)
        .filter(
            WorkOrderTaskLine.id == task_id,
            WorkOrderTaskLine.assigned_mechanic_id == mechanic.id,
            WorkOrder.site_id == active_site_id,
            WorkOrder.status == "EN_PROCESO",
        )
        .first()
    )

    if not task_line:
        return jsonify({"error": "Trabajo no encontrado para este mecánico"}), 404

    if task_line.status != "EN_PROCESO":
        return jsonify({"error": "El trabajo no está en proceso"}), 400

    existing_pending_request = (
        WorkOrderTaskLineFinishRequest.query
        .filter_by(
            task_line_id=task_line.id,
            status="PENDIENTE",
        )
        .first()
    )

    if existing_pending_request:
        return jsonify({"error": "Este trabajo ya tiene una solicitud de finalización pendiente"}), 400

    now = datetime.now(UTC)

    try:
        assignment = (
            WorkOrderTaskLineAssignment.query
            .filter_by(
                task_line_id=task_line.id,
                mechanic_id=mechanic.id,
                ended_at=None,
            )
            .first()
        )

        if assignment:
            assignment.ended_at = now
            assignment.ended_reason = "FINALIZACION_SOLICITADA"

            if assignment.started_at:
                seconds_worked = int((now - assignment.started_at).total_seconds())
                seconds_worked = max(seconds_worked, 0)
                assignment.seconds_worked = seconds_worked
                task_line.effective_seconds = (task_line.effective_seconds or 0) + seconds_worked

        task_line.status = "FINALIZACION_SOLICITADA"
        task_line.finish_requested_at = now

        finish_request = WorkOrderTaskLineFinishRequest(
            task_line_id=task_line.id,
            requested_by_mechanic_id=mechanic.id,
            status="PENDIENTE",
            requested_at=now,
        )

        db.session.add(finish_request)
        db.session.commit()

        return jsonify({
            "ok": True,
            "message": "Solicitud de finalización enviada correctamente.",
        })

    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 500


@terminal_bp.route("/work-orders/<int:work_order_id>/requests/submit", methods=["POST"])
@login_required
def submit_request(work_order_id):
    data = request.get_json(silent=True) or {}
    lines = data.get("lines") or []
    mechanic_id = data.get("mechanic_id")
    active_site_id = session.get("active_site_id")

    if not active_site_id:
        return jsonify({"error": "No hay predio activo seleccionado"}), 400

    if not lines:
        return jsonify({"error": "No hay artículos para solicitar"}), 400

    if not mechanic_id:
        return jsonify({"error": "Falta el mecánico que realizó el escaneo"}), 400

    work_order = WorkOrder.query.filter_by(
        id=work_order_id,
        site_id=active_site_id,
    ).first()

    if not work_order:
        return jsonify({"error": "OT no encontrada"}), 404

    if work_order.status != "EN_PROCESO":
        return jsonify({"error": "La OT no está en proceso"}), 400

    try:
        request_obj = create_request(
            work_order_id=work_order.id,
            requested_by_user_id=current_user.id,
            mechanic_id=int(mechanic_id),
            commit=False,
        )

        db.session.flush()

        for line in lines:
            article_id = line.get("article_id")
            quantity_requested = line.get("quantity")
            notes = line.get("notes")

            if not article_id:
                raise WorkOrderRequestServiceError("Falta el artículo en una de las líneas.")

            add_request_line(
                request_id=request_obj.id,
                article_id=int(article_id),
                quantity_requested=quantity_requested,
                notes=notes,
                commit=False,
            )

        db.session.flush()

        send_request(
            request_id=request_obj.id,
            performed_by_user_id=current_user.id,
            commit=False,
        )

        db.session.commit()

        return jsonify({
            "ok": True,
            "request_id": request_obj.id,
            "message": "Solicitud enviada correctamente.",
        })

    except WorkOrderRequestServiceError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400

    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": f"Error al enviar solicitud: {str(exc)}"}), 500


@terminal_bp.route("/pending-receptions/<int:mechanic_id>")
@login_required
def pending_receptions(mechanic_id):
    active_site_id = session.get("active_site_id")

    if not active_site_id:
        return jsonify({"error": "No hay predio activo seleccionado"}), 400

    mechanic = Mechanic.query.filter_by(
        id=mechanic_id,
        site_id=active_site_id,
        is_active=True,
    ).first()

    if not mechanic:
        return jsonify({"error": "Mecánico no encontrado"}), 404

    requests = (
        WorkOrderRequest.query
        .join(WorkOrder, WorkOrder.id == WorkOrderRequest.work_order_id)
        .filter(
            WorkOrder.site_id == active_site_id,
            WorkOrderRequest.mechanic_id == mechanic_id,
        )
        .all()
    )

    items = []

    for req in requests:
        delivered_lines = []

        for line in req.lines:
            if line.line_status != "ENTREGADA":
                continue

            existing_ot_line = (
                WorkOrderLine.query
                .filter_by(request_line_id=line.id)
                .first()
            )

            if existing_ot_line:
                continue

            delivered_lines.append(line)

        if not delivered_lines:
            continue

        work_order = req.work_order
        equipment_label = (
            work_order.equipment_code_snapshot
            if work_order and work_order.equipment_code_snapshot
            else "Sin equipo"
        )

        articles = [
            {
                "line_id": line.id,
                "article": (
                    f"{line.article.code} - {line.article.name}"
                    if line.article else ""
                ),
                "quantity": str(line.quantity_attended),
            }
            for line in delivered_lines
        ]

        items.append({
            "request_id": req.id,
            "work_order": work_order.number if work_order else "",
            "equipment": equipment_label,
            "articles": articles,
        })

    return jsonify({"items": items})


@terminal_bp.route("/confirm-reception", methods=["POST"])
@login_required
def confirm_reception():
    data = request.get_json(silent=True) or {}

    request_id = data.get("request_id")
    mechanic_code = (data.get("code") or "").strip()
    active_site_id = session.get("active_site_id")

    if not request_id or not mechanic_code:
        return jsonify({"error": "Datos incompletos"}), 400

    if not active_site_id:
        return jsonify({"error": "No hay predio activo seleccionado"}), 400

    mechanic = Mechanic.query.filter_by(
        code=mechanic_code,
        site_id=active_site_id,
        is_active=True,
    ).first()

    if not mechanic:
        return jsonify({"error": "Mecánico no encontrado"}), 404

    request_obj = (
        WorkOrderRequest.query
        .join(WorkOrder, WorkOrder.id == WorkOrderRequest.work_order_id)
        .filter(
            WorkOrderRequest.id == request_id,
            WorkOrder.site_id == active_site_id,
        )
        .first()
    )

    if not request_obj:
        return jsonify({"error": "Solicitud no existe"}), 404

    if request_obj.mechanic_id != mechanic.id:
        return jsonify({
            "error": "Este mecánico no fue quien solicitó esta entrega"
        }), 400

    delivered_lines = []

    for line in request_obj.lines:
        if line.line_status != "ENTREGADA":
            continue

        existing_ot_line = (
            WorkOrderLine.query
            .filter_by(request_line_id=line.id)
            .first()
        )

        if existing_ot_line:
            continue

        delivered_lines.append(line)

    if not delivered_lines:
        return jsonify({"error": "La solicitud no tiene entregas pendientes por recibir"}), 400

    try:
        for line in delivered_lines:
            confirm_request_line_to_work_order(
                request_line_id=line.id,
                delivered_by_user_id=current_user.id,
                received_by_user_id=current_user.id,
                commit=False,
            )

        db.session.commit()
        return jsonify({"ok": True})

    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400

@terminal_bp.route("/articles-tree/<int:warehouse_id>")
@login_required
def get_articles_tree(warehouse_id):
    try:
        items = get_inventory_by_warehouse(warehouse_id)

        data = {}

        for i in items:
            if float(i["quantity_on_hand"]) <= 0:
                continue

            if i["code"] == "19000":
                continue

            category = i.get("category_name") or "Sin categoría"
            subcategory = i.get("subcategory_name") or "Sin subcategoría"

            data.setdefault(category, {})
            data[category].setdefault(subcategory, [])

            data[category][subcategory].append({
                "article_id": i["article_id"],
                "code": i["code"],
                "name": i["name"],
                "stock": i["quantity_on_hand"],
            })

        return jsonify({"data": data})

    except InventoryServiceError as exc:
        return jsonify({"error": str(exc)}), 400