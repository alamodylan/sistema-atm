# routes/work_order_requests.py
from decimal import Decimal, InvalidOperation

from flask import Blueprint, flash, redirect, request, url_for
from flask_login import current_user, login_required
from app.models.work_order_request_line import WorkOrderRequestLine
from app.models.inventory import WarehouseStock

from app.services.work_order_request_service import (
    WorkOrderRequestServiceError,
    add_request_line,
    attend_request_line,
    cancel_request_line,
    confirm_request_line_to_work_order,
    create_request,
    mark_request_line_loaned,
    mark_request_line_not_delivered,
    reject_request_line_by_management,
    send_request,
    send_request_to_warehouse,
    undo_manager_decision,
    update_request_line_requested_quantity,
)

work_order_request_bp = Blueprint("work_order_requests", __name__)


# =========================
# CREAR SOLICITUD
# =========================
@work_order_request_bp.route("/work-orders/<int:work_order_id>/requests", methods=["POST"])
@login_required
def create_request_action(work_order_id: int):
    try:
        create_request(
            work_order_id=work_order_id,
            requested_by_user_id=current_user.id,
            commit=True,
        )
        flash("Solicitud creada.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(url_for("work_orders.get_work_order", work_order_id=work_order_id))


# =========================
# AGREGAR LÍNEA
# =========================
@work_order_request_bp.route("/requests/<int:request_id>/lines", methods=["POST"])
@login_required
def add_request_line_action(request_id: int):
    try:
        article_id = request.form.get("article_id")
        quantity_raw = request.form.get("quantity")
        notes = request.form.get("notes")

        if not article_id or not quantity_raw:
            raise ValueError("Datos incompletos.")

        qty = Decimal(quantity_raw)

        add_request_line(
            request_id=request_id,
            article_id=int(article_id),
            quantity_requested=qty,
            notes=notes,
            commit=True,
        )

        flash("Línea agregada a la solicitud.", "success")

    except (WorkOrderRequestServiceError, ValueError, InvalidOperation) as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# MECÁNICO ENVÍA
# =========================
@work_order_request_bp.route("/requests/<int:request_id>/send", methods=["POST"])
@login_required
def send_request_action(request_id: int):
    try:
        send_request(
            request_id=request_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Solicitud enviada a jefatura.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# JEFATURA → ENVIAR A BODEGA
# =========================
@work_order_request_bp.route("/requests/<int:request_id>/send-to-warehouse", methods=["POST"])
@login_required
def send_request_to_warehouse_action(request_id: int):
    try:
        send_request_to_warehouse(
            request_id=request_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Solicitud enviada a bodega.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# CANCELAR LÍNEA
# =========================
@work_order_request_bp.route("/request-lines/<int:line_id>/cancel", methods=["POST"])
@login_required
def cancel_request_line_action(line_id: int):
    try:
        cancel_request_line(
            request_line_id=line_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Línea cancelada correctamente.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# JEFATURA → APROBAR / AJUSTAR
# =========================
@work_order_request_bp.route("/request-lines/<int:line_id>/approve", methods=["POST"])
@login_required
def approve_request_line_action(line_id: int):
    try:
        # =========================
        # OBTENER LÍNEA
        # =========================
        line = WorkOrderRequestLine.query.get_or_404(line_id)

        qty = Decimal(request.form.get("quantity") or "0")

        # =========================
        # OBTENER STOCK REAL
        # =========================
        stock = (
            WarehouseStock.query
            .filter_by(
                article_id=line.article_id,
                warehouse_id=line.work_order_request.work_order.warehouse_id,
            )
            .first()
        )

        available_qty = Decimal(str(stock.available_quantity if stock else 0))

        # =========================
        # VALIDACIONES
        # =========================

        # 1. Mayor que cero
        if qty <= 0:
            raise ValueError("La cantidad debe ser mayor a cero.")

        # 2. No mayor al stock
        if qty > available_qty:
            raise ValueError("No se puede aprobar más que el stock disponible.")

        # 3. No decimales en UND
        unit_code = line.article.unit.code if line.article and line.article.unit else ""

        if unit_code == "UND":
            if qty != qty.to_integral_value():
                raise ValueError("Este artículo usa unidad UND, solo permite cantidades enteras.")

        # =========================
        # APLICAR APROBACIÓN
        # =========================
        update_request_line_requested_quantity(
            request_line_id=line_id,
            quantity_requested=qty,
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Cantidad aprobada/ajustada.", "success")

    except (WorkOrderRequestServiceError, InvalidOperation, ValueError) as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# JEFATURA → RECHAZAR
# =========================
@work_order_request_bp.route("/request-lines/<int:line_id>/reject", methods=["POST"])
@login_required
def reject_request_line_action(line_id: int):
    try:
        reject_request_line_by_management(
            request_line_id=line_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Línea rechazada.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# JEFATURA → DESHACER DECISIÓN
# =========================
@work_order_request_bp.route("/request-lines/<int:line_id>/undo-manager-decision", methods=["POST"])
@login_required
def undo_manager_decision_action(line_id: int):
    try:
        undo_manager_decision(
            request_line_id=line_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Decisión de jefatura revertida.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# BODEGA → ATENDER
# =========================
@work_order_request_bp.route("/request-lines/<int:line_id>/attend", methods=["POST"])
@login_required
def attend_request_line_action(line_id: int):
    try:
        qty = Decimal(request.form.get("quantity"))

        attend_request_line(
            request_line_id=line_id,
            quantity=qty,
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Línea preparada correctamente.", "success")

    except (WorkOrderRequestServiceError, InvalidOperation, ValueError) as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# BODEGA → NO ENTREGADO
# =========================
@work_order_request_bp.route("/request-lines/<int:line_id>/not-delivered", methods=["POST"])
@login_required
def mark_request_line_not_delivered_action(line_id: int):
    try:
        mark_request_line_not_delivered(
            request_line_id=line_id,
            reason=request.form.get("reason") or "",
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Marcado como no entregado.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# BODEGA → PRESTAR
# =========================
@work_order_request_bp.route("/request-lines/<int:line_id>/loan", methods=["POST"])
@login_required
def mark_request_line_loaned_action(line_id: int):
    try:
        qty = Decimal(request.form.get("quantity"))

        mark_request_line_loaned(
            request_line_id=line_id,
            quantity=qty,
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Línea prestada.", "success")

    except (WorkOrderRequestServiceError, InvalidOperation, ValueError) as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# TERMINAL → CONFIRMAR ENTREGA
# =========================
@work_order_request_bp.route("/request-lines/<int:line_id>/confirm-to-work-order", methods=["POST"])
@login_required
def confirm_request_line_to_work_order_action(line_id: int):
    try:
        confirm_request_line_to_work_order(
            request_line_id=line_id,
            delivered_by_user_id=int(request.form.get("delivered_by_user_id")),
            received_by_user_id=int(request.form.get("received_by_user_id")),
            commit=True,
        )

        flash("Entrega confirmada.", "success")

    except (WorkOrderRequestServiceError, ValueError) as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")