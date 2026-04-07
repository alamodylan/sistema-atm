# app/services/work_order_request_service.py

from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models.article import Article
from app.models.work_order import WorkOrder
from app.models.work_order_request import WorkOrderRequest
from app.models.work_order_request_line import WorkOrderRequestLine
from app.services.audit_service import log_action


class WorkOrderRequestServiceError(Exception):
    pass


TERMINAL_LINE_STATUSES = {"ENTREGADA", "NO_ENTREGADA", "CANCELADA", "PRESTADA"}


def _to_decimal(value) -> Decimal:
    qty = Decimal(str(value))
    if qty <= 0:
        raise WorkOrderRequestServiceError("La cantidad debe ser mayor a 0.")
    return qty


def _sync_request_status(request_obj: WorkOrderRequest) -> None:
    lines = request_obj.lines.all()
    if not lines:
        return

    if all(line.line_status in TERMINAL_LINE_STATUSES for line in lines):
        request_obj.request_status = "ATENDIDA"


def create_request(
    *,
    work_order_id: int,
    requested_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequest:
    work_order = WorkOrder.query.get(work_order_id)
    if not work_order:
        raise WorkOrderRequestServiceError("La OT no existe.")

    if work_order.status != "EN_PROCESO":
        raise WorkOrderRequestServiceError("Solo se pueden crear solicitudes para OTs en proceso.")

    existing_open = (
        WorkOrderRequest.query
        .filter_by(
            work_order_id=work_order_id,
            requested_by_user_id=requested_by_user_id,
            request_status="ABIERTA",
        )
        .order_by(WorkOrderRequest.created_at.desc())
        .first()
    )
    if existing_open:
        return existing_open

    request_obj = WorkOrderRequest(
        work_order_id=work_order_id,
        requested_by_user_id=requested_by_user_id,
        request_status="ABIERTA",
    )

    db.session.add(request_obj)

    if commit:
        db.session.commit()

    log_action(
        user_id=requested_by_user_id,
        action="CREATE_WORK_ORDER_REQUEST",
        table_name="work_order_requests",
        record_id=str(request_obj.id),
        details={"work_order_id": work_order_id},
        commit=commit,
    )

    return request_obj


def add_request_line(
    *,
    request_id: int,
    article_id: int,
    quantity_requested,
    notes: str | None = None,
    commit: bool = True,
) -> WorkOrderRequestLine:
    request_obj = WorkOrderRequest.query.get(request_id)
    if not request_obj:
        raise WorkOrderRequestServiceError("La solicitud no existe.")

    if request_obj.request_status != "ABIERTA":
        raise WorkOrderRequestServiceError("Solo se pueden agregar líneas a solicitudes abiertas.")

    article = Article.query.get(article_id)
    if not article:
        raise WorkOrderRequestServiceError("El artículo no existe.")

    qty = _to_decimal(quantity_requested)

    line = WorkOrderRequestLine(
        work_order_request_id=request_id,
        article_id=article_id,
        quantity_requested=qty,
        quantity_attended=Decimal("0"),
        notes=(notes or "").strip() or None,
        line_status="SOLICITADA",
    )

    db.session.add(line)

    if commit:
        db.session.commit()

    log_action(
        user_id=request_obj.requested_by_user_id,
        action="ADD_WORK_ORDER_REQUEST_LINE",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "request_id": request_id,
            "article_id": article_id,
            "quantity_requested": str(qty),
        },
        commit=commit,
    )

    return line


def cancel_request_line(
    *,
    request_line_id: int,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequestLine:
    line = WorkOrderRequestLine.query.get(request_line_id)
    if not line:
        raise WorkOrderRequestServiceError("La línea no existe.")

    request_obj = line.work_order_request
    if request_obj.request_status != "ABIERTA":
        raise WorkOrderRequestServiceError("Solo se pueden cancelar líneas de solicitudes abiertas.")

    line.line_status = "CANCELADA"
    _sync_request_status(request_obj)

    if commit:
        db.session.commit()

    log_action(
        user_id=performed_by_user_id,
        action="CANCEL_WORK_ORDER_REQUEST_LINE",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={"line_status": line.line_status},
        commit=commit,
    )

    return line


def send_request(
    *,
    request_id: int,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequest:
    request_obj = WorkOrderRequest.query.get(request_id)
    if not request_obj:
        raise WorkOrderRequestServiceError("La solicitud no existe.")

    if request_obj.request_status != "ABIERTA":
        raise WorkOrderRequestServiceError("Solo solicitudes abiertas pueden enviarse.")

    active_lines_count = request_obj.lines.filter(
        WorkOrderRequestLine.line_status != "CANCELADA"
    ).count()

    if active_lines_count == 0:
        raise WorkOrderRequestServiceError("No se puede enviar una solicitud sin líneas activas.")

    request_obj.request_status = "ENVIADA"

    if commit:
        db.session.commit()

    log_action(
        user_id=performed_by_user_id,
        action="SEND_WORK_ORDER_REQUEST",
        table_name="work_order_requests",
        record_id=str(request_obj.id),
        details={"status": request_obj.request_status},
        commit=commit,
    )

    return request_obj


def attend_request_line(
    *,
    request_line_id: int,
    quantity,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequestLine:
    line = WorkOrderRequestLine.query.get(request_line_id)
    if not line:
        raise WorkOrderRequestServiceError("La línea no existe.")

    request_obj = line.work_order_request
    if request_obj.request_status != "ENVIADA":
        raise WorkOrderRequestServiceError("Solo se pueden atender líneas de solicitudes enviadas.")

    qty = _to_decimal(quantity)
    remaining = line.quantity_requested - line.quantity_attended

    if qty > remaining:
        raise WorkOrderRequestServiceError("No puede atender más de lo solicitado.")

    line.quantity_attended += qty

    if line.quantity_attended == line.quantity_requested:
        line.line_status = "ENTREGADA"
    else:
        line.line_status = "ATENDIDA_PARCIAL"

    _sync_request_status(request_obj)

    if commit:
        db.session.commit()

    log_action(
        user_id=performed_by_user_id,
        action="ATTEND_REQUEST_LINE",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "attended": str(qty),
            "total_attended": str(line.quantity_attended),
            "line_status": line.line_status,
        },
        commit=commit,
    )

    return line


def mark_request_line_not_delivered(
    *,
    request_line_id: int,
    reason: str,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequestLine:
    line = WorkOrderRequestLine.query.get(request_line_id)
    if not line:
        raise WorkOrderRequestServiceError("La línea no existe.")

    request_obj = line.work_order_request
    if request_obj.request_status != "ENVIADA":
        raise WorkOrderRequestServiceError("Solo se pueden marcar líneas no entregadas en solicitudes enviadas.")

    line.line_status = "NO_ENTREGADA"
    line.not_delivered_reason = (reason or "").strip() or None

    _sync_request_status(request_obj)

    if commit:
        db.session.commit()

    log_action(
        user_id=performed_by_user_id,
        action="MARK_REQUEST_LINE_NOT_DELIVERED",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "line_status": line.line_status,
            "reason": line.not_delivered_reason,
        },
        commit=commit,
    )

    return line


def mark_request_line_loaned(
    *,
    request_line_id: int,
    quantity,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequestLine:
    line = WorkOrderRequestLine.query.get(request_line_id)
    if not line:
        raise WorkOrderRequestServiceError("La línea no existe.")

    request_obj = line.work_order_request
    if request_obj.request_status != "ENVIADA":
        raise WorkOrderRequestServiceError("Solo se pueden prestar líneas de solicitudes enviadas.")

    qty = _to_decimal(quantity)
    remaining = line.quantity_requested - line.quantity_attended

    if qty > remaining:
        raise WorkOrderRequestServiceError("No puede prestar más de lo solicitado.")

    line.quantity_attended += qty

    if line.quantity_attended == line.quantity_requested:
        line.line_status = "PRESTADA"
    else:
        line.line_status = "ATENDIDA_PARCIAL"

    _sync_request_status(request_obj)

    if commit:
        db.session.commit()

    log_action(
        user_id=performed_by_user_id,
        action="MARK_REQUEST_LINE_LOANED",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "loaned": str(qty),
            "total_attended": str(line.quantity_attended),
            "line_status": line.line_status,
        },
        commit=commit,
    )

    return line