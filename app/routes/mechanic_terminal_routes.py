from flask import Blueprint, render_template, request, jsonify, session
from flask_login import current_user, login_required

from app.models.mechanic import Mechanic
from app.models.work_order import WorkOrder
from app.models.tool_loan import ToolLoan
from app.services.inventory_service import get_inventory_by_warehouse, InventoryServiceError
from app.extensions import db
from app.models.work_order_request import WorkOrderRequest
from app.models.work_order_request_line import WorkOrderRequestLine

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

    work_orders = [
        {
            "id": ot.id,
            "number": ot.number,
            "warehouse_id": ot.warehouse_id,
            "equipment_code_snapshot": ot.equipment_code_snapshot,
        }
        for ot in mechanic.work_orders
        if ot.status == "EN_PROCESO"
    ]

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



@terminal_bp.route("/work-orders/<int:work_order_id>/requests/submit", methods=["POST"])
@login_required
def submit_request(work_order_id):
    data = request.get_json(silent=True) or {}
    lines = data.get("lines") or []

    if not lines:
        return jsonify({"error": "No hay líneas para solicitar"}), 400

    active_site_id = session.get("active_site_id")

    if not active_site_id:
        return jsonify({"error": "No hay predio activo"}), 400

    # 🔹 validar OT
    work_order = WorkOrder.query.filter_by(
        id=work_order_id,
        site_id=active_site_id,
    ).first()

    if not work_order:
        return jsonify({"error": "OT no encontrada"}), 404

    if work_order.status != "EN_PROCESO":
        return jsonify({"error": "La OT no está en proceso"}), 400

    try:
        # 🔥 buscar solicitud existente
        request_obj = WorkOrderRequest.query.filter_by(
            work_order_id=work_order_id
        ).first()

        # 🔥 si no existe → crearla
        if not request_obj:
            request_obj = WorkOrderRequest(
                work_order_id=work_order_id,
                created_by_user_id=current_user.id,
            )
            db.session.add(request_obj)
            db.session.flush()  # 🔥 necesario para obtener id

        # 🔥 insertar líneas
        for line in lines:
            new_line = WorkOrderRequestLine(
                work_order_request_id=request_obj.id,
                article_id=line["article_id"],
                quantity=line["quantity"],
                created_by_user_id=current_user.id,
            )
            db.session.add(new_line)

        db.session.commit()

        return jsonify({"ok": True})

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500