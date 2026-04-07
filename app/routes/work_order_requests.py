# app/routes/work_order_requests.py

from decimal import Decimal, InvalidOperation

from flask import Blueprint, flash, redirect, request, url_for, jsonify
from flask_login import current_user, login_required

from app.models.work_order_request import WorkOrderRequest
from app.services.work_order_request_service import (
    WorkOrderRequestServiceError,
    create_request,
    add_request_line,
    send_request,
    attend_request_line,
)

work_order_request_bp = Blueprint("work_order_requests", __name__)


# =========================================================
# CREAR SOLICITUD
# =========================================================
@work_order_request_bp.route("/work-orders/<int:work_order_id>/requests", methods=["POST"])
@login_required
def create_request_action(work_order_id: int):
    try:
        req = create_request(
            work_order_id=work_order_id,
            requested_by_user_id=current_user.id,
            commit=True,
        )

        flash("Solicitud creada.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(url_for("work_orders.get_work_order", work_order_id=work_order_id))


# =========================================================
# AGREGAR LÍNEA A SOLICITUD
# =========================================================
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


# =========================================================
# ENVIAR SOLICITUD
# =========================================================
@work_order_request_bp.route("/requests/<int:request_id>/send", methods=["POST"])
@login_required
def send_request_action(request_id: int):
    try:
        send_request(
            request_id=request_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Solicitud enviada a bodega.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================================================
# ATENDER LÍNEA (BODEGA)
# =========================================================
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


# =========================================================
# TERMINAL: CREAR + AGREGAR LÍNEAS + ENVIAR
# =========================================================
@work_order_request_bp.route("/terminal/work-orders/<int:work_order_id>/requests/submit", methods=["POST"])
@login_required
def terminal_submit_request_action(work_order_id: int):
    try:
        data = request.get_json(silent=True) or {}
        lines = data.get("lines") or []
        notes = data.get("notes")

        if not lines:
            raise ValueError("Debe agregar al menos una línea.")

        # reutiliza solicitud abierta si ya existe para esa OT y usuario
        req = (
            WorkOrderRequest.query
            .filter_by(
                work_order_id=work_order_id,
                requested_by_user_id=current_user.id,
                request_status="ABIERTA",
            )
            .order_by(WorkOrderRequest.created_at.desc())
            .first()
        )

        if not req:
            req = create_request(
                work_order_id=work_order_id,
                requested_by_user_id=current_user.id,
                commit=False,
            )

        for line in lines:
            article_id = line.get("article_id")
            quantity_raw = line.get("quantity")

            if not article_id or quantity_raw is None:
                raise ValueError("Cada línea debe incluir artículo y cantidad.")

            try:
                qty = Decimal(str(quantity_raw))
            except (InvalidOperation, ValueError):
                raise ValueError("Cantidad inválida en una de las líneas.")

            add_request_line(
                request_id=req.id,
                article_id=int(article_id),
                quantity_requested=qty,
                notes=notes,
                commit=False,
            )

        send_request(
            request_id=req.id,
            performed_by_user_id=current_user.id,
            commit=True,
        )

        return jsonify({
            "ok": True,
            "request_id": req.id,
            "message": "Solicitud enviada a bodega.",
        })

    except (WorkOrderRequestServiceError, ValueError) as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 400

    except Exception:
        return jsonify({
            "ok": False,
            "error": "Error interno al enviar la solicitud.",
        }), 500