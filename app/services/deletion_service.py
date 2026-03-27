from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.extensions import db
from app.models.deletion_request import WorkOrderLineDeleteRequest
from app.models.work_order_line import WorkOrderLine
from app.services.audit_service import log_action
from app.services.inventory_service import InventoryServiceError, add_stock


class DeletionServiceError(Exception):
    pass


def create_deletion_request(
    *,
    work_order_line_id: int,
    requested_by_user_id: int,
    reason: str,
    commit: bool = True,
) -> WorkOrderLineDeleteRequest:
    line = WorkOrderLine.query.get(work_order_line_id)
    if not line:
        raise DeletionServiceError("La línea de OT no existe.")

    if not reason or not reason.strip():
        raise DeletionServiceError("El motivo es obligatorio.")

    if line.line_status == "REMOVED":
        raise DeletionServiceError("La línea ya fue eliminada anteriormente.")

    existing_pending = line.delete_requests.filter_by(status="PENDIENTE").first()
    if existing_pending:
        raise DeletionServiceError("Ya existe una solicitud de eliminación pendiente para esta línea.")

    request_obj = WorkOrderLineDeleteRequest(
        work_order_line_id=work_order_line_id,
        requested_by_user_id=requested_by_user_id,
        reason=reason.strip(),
        status="PENDIENTE",
    )

    line.line_status = "REMOVAL_PENDING"

    db.session.add(request_obj)

    log_action(
        user_id=requested_by_user_id,
        action="CREATE_DELETION_REQUEST",
        table_name="work_order_line_delete_requests",
        record_id=str(request_obj.id) if request_obj.id else f"pending:{work_order_line_id}",
        details={
            "work_order_line_id": work_order_line_id,
            "reason": reason.strip(),
            "line_status": line.line_status,
        },
        commit=False,
    )

    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    return request_obj


def approve_deletion_request(
    *,
    deletion_request_id: int,
    reviewed_by_user_id: int,
    review_notes: str | None = None,
    commit: bool = True,
) -> WorkOrderLineDeleteRequest:
    request_obj = WorkOrderLineDeleteRequest.query.get(deletion_request_id)
    if not request_obj:
        raise DeletionServiceError("La solicitud de eliminación no existe.")

    if request_obj.status != "PENDIENTE":
        raise DeletionServiceError("Solo se pueden aprobar solicitudes pendientes.")

    line = request_obj.work_order_line
    if not line:
        raise DeletionServiceError("La línea asociada ya no existe.")

    reversed_qty = Decimal("0.00")

    if line.inventory_posted:
        reversed_qty = Decimal(str(line.quantity or 0))

        if reversed_qty > 0:
            try:
                add_stock(
                    article_id=line.article_id,
                    warehouse_id=line.work_order.warehouse_id,
                    quantity=reversed_qty,
                    performed_by_user_id=reviewed_by_user_id,
                    movement_type="REVERSO_ELIMINACION_LINEA_OT",
                    reason=f"Reverso por aprobación de eliminación de línea OT {line.work_order.number}",
                    reference_type="WORK_ORDER_LINE",
                    reference_id=line.id,
                    reference_number=line.work_order.number,
                    commit=False,
                )
            except InventoryServiceError as exc:
                db.session.rollback()
                raise DeletionServiceError(str(exc)) from exc

        line.inventory_posted = False

    line.line_status = "REMOVED"

    request_obj.status = "APROBADA"
    request_obj.reviewed_by_user_id = reviewed_by_user_id
    request_obj.reviewed_at = datetime.now(UTC)
    request_obj.review_notes = (review_notes or "").strip() or None

    log_action(
        user_id=reviewed_by_user_id,
        action="APPROVE_DELETION_REQUEST",
        table_name="work_order_line_delete_requests",
        record_id=str(request_obj.id),
        details={
            "work_order_line_id": line.id,
            "article_id": line.article_id,
            "reversed_quantity": str(reversed_qty),
            "inventory_posted_after": line.inventory_posted,
            "line_status_after": line.line_status,
            "review_notes": request_obj.review_notes,
        },
        commit=False,
    )

    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    return request_obj


def reject_deletion_request(
    *,
    deletion_request_id: int,
    reviewed_by_user_id: int,
    review_notes: str | None = None,
    commit: bool = True,
) -> WorkOrderLineDeleteRequest:
    request_obj = WorkOrderLineDeleteRequest.query.get(deletion_request_id)
    if not request_obj:
        raise DeletionServiceError("La solicitud de eliminación no existe.")

    if request_obj.status != "PENDIENTE":
        raise DeletionServiceError("Solo se pueden rechazar solicitudes pendientes.")

    line = request_obj.work_order_line
    if not line:
        raise DeletionServiceError("La línea asociada ya no existe.")

    request_obj.status = "RECHAZADA"
    request_obj.reviewed_by_user_id = reviewed_by_user_id
    request_obj.reviewed_at = datetime.now(UTC)
    request_obj.review_notes = (review_notes or "").strip() or None

    if line.line_status == "REMOVAL_PENDING":
        line.line_status = "ACTIVE"

    log_action(
        user_id=reviewed_by_user_id,
        action="REJECT_DELETION_REQUEST",
        table_name="work_order_line_delete_requests",
        record_id=str(request_obj.id),
        details={
            "work_order_line_id": request_obj.work_order_line_id,
            "line_status_after": line.line_status,
            "review_notes": request_obj.review_notes,
        },
        commit=False,
    )

    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    return request_obj