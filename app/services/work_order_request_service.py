from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models.article import Article
from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLine
from app.models.work_order_request import WorkOrderRequest
from app.models.work_order_request_line import WorkOrderRequestLine
from app.services.audit_service import log_action
from app.services.inventory_service import (
    InventoryServiceError,
    get_warehouse_stock_record,
    subtract_stock,
)


class WorkOrderRequestServiceError(Exception):
    pass


TERMINAL_LINE_STATUSES = {"ENTREGADA", "NO_ENTREGADA", "CANCELADA", "PRESTADA"}


def _to_decimal(value) -> Decimal:
    qty = Decimal(str(value))
    if qty <= 0:
        raise WorkOrderRequestServiceError("La cantidad debe ser mayor a 0.")
    return qty


def _sync_request_status(request_obj: WorkOrderRequest) -> None:
    lines = list(request_obj.lines)
    if not lines:
        return

    active_lines = [line for line in lines if line.line_status != "CANCELADA"]

    if not active_lines:
        request_obj.request_status = "CANCELADA"
        return

    if all(line.line_status in TERMINAL_LINE_STATUSES for line in active_lines):
        request_obj.request_status = "ATENDIDA"
        return

    if request_obj.request_status == "CANCELADA":
        request_obj.request_status = "ENVIADA"


def create_request(
    *,
    work_order_id: int,
    requested_by_user_id: int,
    mechanic_id: int | None = None,
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
        mechanic_id=mechanic_id,
        request_status="ABIERTA",
    )

    db.session.add(request_obj)
    db.session.flush()

    log_action(
        user_id=requested_by_user_id,
        action="CREATE_WORK_ORDER_REQUEST",
        table_name="work_order_requests",
        record_id=str(request_obj.id),
        details={
            "work_order_id": work_order_id,
            "mechanic_id": mechanic_id,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return request_obj


def add_request_line(
    *,
    request_id: int,
    article_id: int,
    quantity_requested,
    notes: str | None = None,
    commit: bool = True,
) -> WorkOrderRequestLine:
    if not request_id:
        raise WorkOrderRequestServiceError("La solicitud no existe.")

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
        manager_review_status="PENDIENTE",
    )

    db.session.add(line)
    db.session.flush()

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
        commit=False,
    )

    if commit:
        db.session.commit()

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
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="CANCEL_WORK_ORDER_REQUEST_LINE",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={"line_status": line.line_status},
        commit=False,
    )

    if commit:
        db.session.commit()

    return line


def reject_request_line_by_management(
    *,
    request_line_id: int,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequestLine:
    line = WorkOrderRequestLine.query.get(request_line_id)
    if not line:
        raise WorkOrderRequestServiceError("La línea no existe.")

    request_obj = line.work_order_request
    if request_obj.request_status != "ENVIADA":
        raise WorkOrderRequestServiceError("Solo se pueden rechazar líneas de solicitudes enviadas.")

    if request_obj.sent_to_warehouse_at:
        raise WorkOrderRequestServiceError("La solicitud ya fue enviada a bodega y no puede rechazarse desde jefatura.")

    line.manager_review_status = "RECHAZADA"
    line.manager_reviewed_by_user_id = performed_by_user_id
    line.manager_reviewed_at = db.func.now()
    line.line_status = "CANCELADA"

    _sync_request_status(request_obj)
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="REJECT_REQUEST_LINE_BY_MANAGEMENT",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "request_id": request_obj.id,
            "line_status": line.line_status,
            "manager_review_status": line.manager_review_status,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return line


def update_request_line_requested_quantity(
    *,
    request_line_id: int,
    quantity_requested,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequestLine:
    line = WorkOrderRequestLine.query.get(request_line_id)
    if not line:
        raise WorkOrderRequestServiceError("La línea no existe.")

    request_obj = line.work_order_request
    if request_obj.request_status != "ENVIADA":
        raise WorkOrderRequestServiceError("Solo se puede modificar cantidad en solicitudes enviadas.")

    if request_obj.sent_to_warehouse_at:
        raise WorkOrderRequestServiceError("La solicitud ya fue enviada a bodega y no puede modificarse desde jefatura.")

    if line.line_status == "CANCELADA":
        raise WorkOrderRequestServiceError("No se puede modificar una línea cancelada.")

    qty = _to_decimal(quantity_requested)

    line.manager_review_status = "APROBADA"
    line.manager_reviewed_by_user_id = performed_by_user_id
    line.manager_reviewed_at = db.func.now()

    line.quantity_requested = qty

    if line.quantity_attended > qty:
        line.quantity_attended = qty

    if line.quantity_attended == 0:
        line.line_status = "SOLICITADA"
    elif line.quantity_attended < line.quantity_requested:
        line.line_status = "ATENDIDA_PARCIAL"
    else:
        line.line_status = "ENTREGADA"

    _sync_request_status(request_obj)
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="UPDATE_REQUEST_LINE_REQUESTED_QUANTITY",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "request_id": request_obj.id,
            "new_quantity_requested": str(qty),
            "line_status": line.line_status,
            "manager_review_status": line.manager_review_status,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return line


def undo_manager_decision(
    *,
    request_line_id: int,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequestLine:
    line = WorkOrderRequestLine.query.get(request_line_id)
    if not line:
        raise WorkOrderRequestServiceError("La línea no existe.")

    request_obj = line.work_order_request
    if request_obj.request_status != "ENVIADA":
        raise WorkOrderRequestServiceError("Solo se puede deshacer en solicitudes enviadas a jefatura.")

    if request_obj.sent_to_warehouse_at:
        raise WorkOrderRequestServiceError("La solicitud ya fue enviada a bodega y no puede revertirse.")

    line.manager_review_status = "PENDIENTE"
    line.manager_reviewed_by_user_id = None
    line.manager_reviewed_at = None
    line.line_status = "SOLICITADA"
    line.not_delivered_reason = None

    _sync_request_status(request_obj)
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="UNDO_MANAGER_DECISION",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "request_id": request_obj.id,
            "manager_review_status": line.manager_review_status,
            "line_status": line.line_status,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return line


def send_request(
    *,
    request_id: int,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequest:
    if not request_id:
        raise WorkOrderRequestServiceError("La solicitud no existe.")

    request_obj = WorkOrderRequest.query.get(request_id)
    if not request_obj:
        raise WorkOrderRequestServiceError("La solicitud no existe.")

    if request_obj.request_status != "ABIERTA":
        raise WorkOrderRequestServiceError("Solo solicitudes abiertas pueden enviarse.")

    active_lines_count = sum(
        1 for line in request_obj.lines
        if line.line_status != "CANCELADA"
    )

    if active_lines_count == 0:
        raise WorkOrderRequestServiceError("No se puede enviar una solicitud sin líneas activas.")

    request_obj.request_status = "ENVIADA"
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="SEND_WORK_ORDER_REQUEST",
        table_name="work_order_requests",
        record_id=str(request_obj.id),
        details={"status": request_obj.request_status},
        commit=False,
    )

    if commit:
        db.session.commit()

    return request_obj


def send_request_to_warehouse(
    *,
    request_id: int,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequest:
    request_obj = WorkOrderRequest.query.get(request_id)
    if not request_obj:
        raise WorkOrderRequestServiceError("La solicitud no existe.")

    if request_obj.request_status != "ENVIADA":
        raise WorkOrderRequestServiceError("Solo solicitudes enviadas por mecánico pueden pasar a bodega.")

    if request_obj.sent_to_warehouse_at:
        raise WorkOrderRequestServiceError("La solicitud ya fue enviada a bodega.")

    lines = list(request_obj.lines)

    if not lines:
        raise WorkOrderRequestServiceError("No hay líneas en la solicitud.")

    has_approved = False

    for line in lines:
        if line.manager_review_status == "PENDIENTE":
            raise WorkOrderRequestServiceError("Debe decidir todas las líneas antes de enviar a bodega.")

        if line.manager_review_status == "APROBADA":
            has_approved = True

    if not has_approved:
        raise WorkOrderRequestServiceError("Debe haber al menos una línea aprobada.")

    request_obj.approved_by_user_id = performed_by_user_id
    request_obj.approved_at = db.func.now()
    request_obj.sent_to_warehouse_by_user_id = performed_by_user_id
    request_obj.sent_to_warehouse_at = db.func.now()

    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="SEND_REQUEST_TO_WAREHOUSE",
        table_name="work_order_requests",
        record_id=str(request_obj.id),
        details={
            "approved_by_user_id": performed_by_user_id,
            "sent_to_warehouse_by_user_id": performed_by_user_id,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

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

    if not request_obj.sent_to_warehouse_at:
        raise WorkOrderRequestServiceError("La solicitud aún no ha sido enviada a bodega.")

    if line.line_status == "CANCELADA":
        raise WorkOrderRequestServiceError("No se puede atender una línea cancelada.")

    if line.manager_review_status != "APROBADA":
        raise WorkOrderRequestServiceError("La línea no fue aprobada por jefatura.")

    qty = _to_decimal(quantity)

    remaining = line.quantity_requested - line.quantity_attended

    work_order = request_obj.work_order
    stock_record = get_warehouse_stock_record(line.article_id, work_order.warehouse_id)

    if not stock_record:
        raise WorkOrderRequestServiceError("No hay stock registrado para este artículo en la bodega de la OT.")

    available = Decimal(str(stock_record.available_quantity or 0))

    # ==============================
    # 🔥 NUEVA REGLA DE NEGOCIO
    # ==============================

    if available >= remaining:
        # ✔ Hay stock suficiente → debe entregar EXACTO
        if qty != remaining:
            raise WorkOrderRequestServiceError(
                f"Debe entregar exactamente {remaining} unidades (cantidad aprobada por jefatura)."
            )
    else:
        # ✔ No hay stock suficiente → puede entregar lo disponible
        if qty > available:
            raise WorkOrderRequestServiceError(
                f"No puede entregar más de lo disponible en stock ({available})."
            )

    if qty > remaining:
        raise WorkOrderRequestServiceError("No puede atender más de lo solicitado.")

    # ==============================

    line.quantity_attended += qty

    if line.quantity_attended == line.quantity_requested:
        line.line_status = "ENTREGADA"
    else:
        line.line_status = "ATENDIDA_PARCIAL"

    _sync_request_status(request_obj)
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="ATTEND_REQUEST_LINE",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "attended": str(qty),
            "total_attended": str(line.quantity_attended),
            "line_status": line.line_status,
            "warehouse_id": work_order.warehouse_id,
            "available_quantity": str(available),
        },
        commit=False,
    )

    if commit:
        db.session.commit()

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

    if not request_obj.sent_to_warehouse_at:
        raise WorkOrderRequestServiceError("La solicitud aún no ha sido enviada a bodega.")

    if line.manager_review_status != "APROBADA":
        raise WorkOrderRequestServiceError("La línea no fue aprobada por jefatura.")

    line.line_status = "NO_ENTREGADA"
    line.not_delivered_reason = (reason or "").strip() or None

    _sync_request_status(request_obj)
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="MARK_REQUEST_LINE_NOT_DELIVERED",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "line_status": line.line_status,
            "reason": line.not_delivered_reason,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

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

    if not request_obj.sent_to_warehouse_at:
        raise WorkOrderRequestServiceError("La solicitud aún no ha sido enviada a bodega.")

    if line.manager_review_status != "APROBADA":
        raise WorkOrderRequestServiceError("La línea no fue aprobada por jefatura.")

    qty = _to_decimal(quantity)
    remaining = line.quantity_requested - line.quantity_attended

    if qty > remaining:
        raise WorkOrderRequestServiceError("No puede prestar más de lo solicitado.")

    work_order = request_obj.work_order
    stock_record = get_warehouse_stock_record(line.article_id, work_order.warehouse_id)

    if not stock_record:
        raise WorkOrderRequestServiceError("No hay stock registrado para este artículo en la bodega de la OT.")

    available = Decimal(str(stock_record.available_quantity or 0))
    if qty > available:
        raise WorkOrderRequestServiceError("No hay suficiente stock disponible para esa cantidad.")

    line.quantity_attended += qty

    if line.quantity_attended == line.quantity_requested:
        line.line_status = "PRESTADA"
    else:
        line.line_status = "ATENDIDA_PARCIAL"

    _sync_request_status(request_obj)
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="MARK_REQUEST_LINE_LOANED",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "loaned": str(qty),
            "total_attended": str(line.quantity_attended),
            "line_status": line.line_status,
            "warehouse_id": work_order.warehouse_id,
            "available_quantity": str(available),
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return line


def confirm_request_line_to_work_order(
    *,
    request_line_id: int,
    delivered_by_user_id: int,
    received_by_user_id: int,
    commit: bool = True,
) -> WorkOrderLine:
    line = WorkOrderRequestLine.query.get(request_line_id)
    if not line:
        raise WorkOrderRequestServiceError("La línea no existe.")

    if line.line_status not in ("ENTREGADA", "PRESTADA"):
        raise WorkOrderRequestServiceError("La línea aún no está lista para confirmarse en la OT.")

    request_obj = line.work_order_request
    work_order = request_obj.work_order

    existing_line = (
        WorkOrderLine.query
        .filter_by(request_line_id=line.id)
        .first()
    )
    if existing_line:
        raise WorkOrderRequestServiceError("Esta línea ya fue confirmada en la OT.")

    qty = Decimal(str(line.quantity_attended or 0))
    if qty <= 0:
        raise WorkOrderRequestServiceError("La línea no tiene cantidad atendida para confirmar.")

    try:
        subtract_stock(
            article_id=line.article_id,
            warehouse_id=work_order.warehouse_id,
            quantity=qty,
            performed_by_user_id=delivered_by_user_id,
            movement_type="SALIDA_OT",
            reason=f"Salida por OT {work_order.number}",
            reference_type="WORK_ORDER",
            reference_id=work_order.id,
            reference_number=work_order.number,
            commit=False,
        )
    except InventoryServiceError as exc:
        raise WorkOrderRequestServiceError(str(exc)) from exc

    work_order_line = WorkOrderLine(
        work_order_id=work_order.id,
        request_line_id=line.id,
        article_id=line.article_id,
        quantity=qty,
        delivered_by_user_id=delivered_by_user_id,
        received_by_user_id=received_by_user_id,
        line_status="ACTIVE",
        inventory_posted=True,
        notes=line.notes,
    )

    db.session.add(work_order_line)
    db.session.flush()

    log_action(
        user_id=received_by_user_id,
        action="CONFIRM_REQUEST_LINE_TO_WORK_ORDER",
        table_name="work_order_lines",
        record_id=str(work_order_line.id),
        details={
            "work_order_id": work_order.id,
            "request_line_id": line.id,
            "article_id": line.article_id,
            "quantity": str(qty),
            "delivered_by_user_id": delivered_by_user_id,
            "received_by_user_id": received_by_user_id,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return work_order_line