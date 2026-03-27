from flask import Blueprint, flash, redirect, request, url_for
from flask_login import current_user, login_required

from app.services.deletion_service import (
    DeletionServiceError,
    create_deletion_request,
    approve_deletion_request,
    reject_deletion_request,
)

deletion_bp = Blueprint("deletions", __name__)


# =========================================================
# CREAR SOLICITUD DE ELIMINACIÓN
# =========================================================
@deletion_bp.route("/requests", methods=["POST"])
@login_required
def create_request():
    try:
        work_order_line_id = request.form.get("work_order_line_id")
        reason = (request.form.get("reason") or "").strip()

        if not work_order_line_id:
            raise ValueError("Debe especificar la línea de la OT.")

        if not reason:
            raise ValueError("Debe indicar un motivo para la eliminación.")

        create_deletion_request(
            work_order_line_id=int(work_order_line_id),
            requested_by_user_id=current_user.id,
            reason=reason,
            commit=True,
        )

        flash("Solicitud de eliminación registrada correctamente.", "success")

    except (DeletionServiceError, ValueError) as exc:
        flash(str(exc), "danger")

    except Exception:
        flash("Error interno al crear la solicitud.", "danger")

    return redirect(request.referrer or url_for("work_orders.list_work_orders"))


# =========================================================
# APROBAR SOLICITUD
# =========================================================
@deletion_bp.route("/requests/<int:request_id>/approve", methods=["POST"])
@login_required
def approve_request(request_id: int):
    try:
        review_notes = (request.form.get("review_notes") or "").strip()

        approve_deletion_request(
            deletion_request_id=request_id,
            reviewed_by_user_id=current_user.id,
            review_notes=review_notes,
            commit=True,
        )

        flash("Solicitud aprobada correctamente.", "success")

    except DeletionServiceError as exc:
        flash(str(exc), "danger")

    except Exception:
        flash("Error interno al aprobar la solicitud.", "danger")

    return redirect(request.referrer or url_for("work_orders.list_work_orders"))


# =========================================================
# RECHAZAR SOLICITUD
# =========================================================
@deletion_bp.route("/requests/<int:request_id>/reject", methods=["POST"])
@login_required
def reject_request(request_id: int):
    try:
        review_notes = (request.form.get("review_notes") or "").strip()

        reject_deletion_request(
            deletion_request_id=request_id,
            reviewed_by_user_id=current_user.id,
            review_notes=review_notes,
            commit=True,
        )

        flash("Solicitud rechazada correctamente.", "success")

    except DeletionServiceError as exc:
        flash(str(exc), "danger")

    except Exception:
        flash("Error interno al rechazar la solicitud.", "danger")

    return redirect(request.referrer or url_for("work_orders.list_work_orders"))