from decimal import Decimal, InvalidOperation

from flask import Blueprint, flash, redirect, request, url_for
from flask_login import current_user, login_required

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
    update_request_line_requested_quantity,
)

work_order_request_bp = Blueprint("work_order_requests", __name__)


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


@work_order_request_bp.route("/requests/<int:request_id>/lines", methods=["POST"])
@login_required
def add_request_line_action(request_id: int):
    try:
        article_id = request.form.get("article_id")
        quantity_raw = request.form.get("quantity")
        notes = request.form.get("notes")

        if not article_id or not quantity_raw:
            raise ValueError("Datos incompletos.")

        try:
            qty = Decimal(quantity_raw)
        except (InvalidOperation, ValueError):
            raise ValueError("Cantidad inválida.")

        add_request_line(
            request_id=request_id,
            article_id=int(article_id),
            quantity_requested=qty,
            notes=notes,
            commit=True,
        )

        flash("Línea agregada a la solicitud.", "success")

    except (WorkOrderRequestServiceError, ValueError) as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


@work_order_request_bp.route("/requests/<int:request_id>/send", methods=["POST"])
@login_required
def send_request_action(request_id: int):
    try:
        send_request(
            request_id=request_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Solicitud enviada.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


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


@work_order_request_bp.route("/request-lines/<int:line_id>/management-update", methods=["POST"])
@login_required
def management_update_request_line_action(line_id: int):
    try:
        quantity_raw = request.form.get("quantity")
        reject = request.form.get("reject")

        if reject == "1":
            reject_request_line_by_management(
                request_line_id=line_id,
                performed_by_user_id=current_user.id,
                commit=True,
            )
            flash("Línea rechazada por jefatura.", "success")
            return redirect(request.referrer or "/")

        if not quantity_raw:
            raise ValueError("Debe indicar una cantidad.")

        try:
            qty = Decimal(quantity_raw)
        except (InvalidOperation, ValueError):
            raise ValueError("Cantidad inválida.")

        update_request_line_requested_quantity(
            request_line_id=line_id,
            quantity_requested=qty,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Cantidad ajustada por jefatura.", "success")

    except (WorkOrderRequestServiceError, ValueError) as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


@work_order_request_bp.route("/request-lines/<int:line_id>/attend", methods=["POST"])
@login_required
def attend_request_line_action(line_id: int):
    try:
        quantity_raw = request.form.get("quantity")

        try:
            qty = Decimal(quantity_raw)
        except (InvalidOperation, ValueError):
            raise ValueError("Cantidad inválida.")

        attend_request_line(
            request_line_id=line_id,
            quantity=qty,
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Línea atendida correctamente.", "success")

    except (WorkOrderRequestServiceError, ValueError) as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


@work_order_request_bp.route("/request-lines/<int:line_id>/not-delivered", methods=["POST"])
@login_required
def mark_request_line_not_delivered_action(line_id: int):
    try:
        reason = request.form.get("reason")

        mark_request_line_not_delivered(
            request_line_id=line_id,
            reason=reason or "",
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Línea marcada como no entregada.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


@work_order_request_bp.route("/request-lines/<int:line_id>/loan", methods=["POST"])
@login_required
def mark_request_line_loaned_action(line_id: int):
    try:
        quantity_raw = request.form.get("quantity")

        try:
            qty = Decimal(quantity_raw)
        except (InvalidOperation, ValueError):
            raise ValueError("Cantidad inválida.")

        mark_request_line_loaned(
            request_line_id=line_id,
            quantity=qty,
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Línea prestada correctamente.", "success")

    except (WorkOrderRequestServiceError, ValueError) as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


@work_order_request_bp.route("/request-lines/<int:line_id>/confirm-to-work-order", methods=["POST"])
@login_required
def confirm_request_line_to_work_order_action(line_id: int):
    try:
        delivered_by_user_id_raw = request.form.get("delivered_by_user_id")
        received_by_user_id_raw = request.form.get("received_by_user_id")

        if not delivered_by_user_id_raw or not received_by_user_id_raw:
            raise ValueError("Faltan usuarios de entrega o recepción.")

        confirm_request_line_to_work_order(
            request_line_id=line_id,
            delivered_by_user_id=int(delivered_by_user_id_raw),
            received_by_user_id=int(received_by_user_id_raw),
            commit=True,
        )

        flash("Entrega confirmada y agregada a la OT.", "success")

    except (WorkOrderRequestServiceError, ValueError) as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")