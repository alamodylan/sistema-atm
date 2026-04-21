from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.extensions import db
from app.models.article import Article
from app.models.inventory import InventoryLedger, WarehouseStock
from app.models.transfer import Transfer
from app.models.transfer_event import TransferEvent
from app.models.transfer_line import TransferLine
from app.models.transfer_request import TransferRequest
from app.models.transfer_request_line import TransferRequestLine
from app.models.user_warehouse_access import UserWarehouseAccess
from app.models.warehouse import Warehouse
from app.services.audit_service import log_action
from app.models.user import User


class TransferServiceError(Exception):
    pass


REQUEST_STATUS_BORRADOR = "BORRADOR"
REQUEST_STATUS_ENVIADA = "ENVIADA"
REQUEST_STATUS_APROBADA = "APROBADA"
REQUEST_STATUS_RECHAZADA = "RECHAZADA"
REQUEST_STATUS_ATENDIDA_PARCIAL = "ATENDIDA_PARCIAL"
REQUEST_STATUS_ATENDIDA = "ATENDIDA"

REQUEST_LINE_REVIEW_PENDIENTE = "PENDIENTE"
REQUEST_LINE_REVIEW_APROBADA = "APROBADA"
REQUEST_LINE_REVIEW_RECHAZADA = "RECHAZADA"

REQUEST_LINE_STATUS_SOLICITADA = "SOLICITADA"
REQUEST_LINE_STATUS_APROBADA = "APROBADA"
REQUEST_LINE_STATUS_ATENDIDA_PARCIAL = "ATENDIDA_PARCIAL"
REQUEST_LINE_STATUS_ATENDIDA = "ATENDIDA"
REQUEST_LINE_STATUS_NO_ATENDIDA = "NO_ATENDIDA"
REQUEST_LINE_STATUS_CANCELADA = "CANCELADA"

TRANSFER_STATUS_BORRADOR = "BORRADOR"
TRANSFER_STATUS_EN_TRANSITO = "EN_TRANSITO"
TRANSFER_STATUS_RECIBIDO = "RECIBIDO"
TRANSFER_STATUS_CANCELADO = "CANCELADO"

TRANSFER_LINE_STATUS_BORRADOR = "BORRADOR"
TRANSFER_LINE_STATUS_PREPARADA = "PREPARADA"
TRANSFER_LINE_STATUS_EN_TRANSITO = "EN_TRANSITO"
TRANSFER_LINE_STATUS_RECIBIDA = "RECIBIDA"


def _now() -> datetime:
    return datetime.now(UTC)


def _to_decimal(value, *, field_name: str = "cantidad") -> Decimal:
    try:
        qty = Decimal(str(value))
    except Exception as exc:
        raise TransferServiceError(f"La {field_name} no es válida.") from exc

    if qty <= 0:
        raise TransferServiceError(f"La {field_name} debe ser mayor a 0.")

    return qty


def _build_number(prefix: str) -> str:
    """
    Generador simple de consecutivo temporal.
    No inventa columnas; solo llena el campo 'number' que ya existe.
    """
    return f"{prefix}-{_now().strftime('%Y%m%d%H%M%S%f')}"


def _append_note(base: str | None, extra: str | None) -> str | None:
    base_clean = (base or "").strip()
    extra_clean = (extra or "").strip()

    if base_clean and extra_clean:
        return f"{base_clean}\n{extra_clean}"
    if extra_clean:
        return extra_clean
    return base_clean or None


def _get_user_accessible_warehouse_ids(user_id: int) -> set[int]:
    rows = (
        UserWarehouseAccess.query
        .filter(UserWarehouseAccess.user_id == user_id)
        .all()
    )
    return {row.warehouse_id for row in rows}


def _validate_user_warehouse_access(user_id: int, warehouse_id: int) -> None:
    user = User.query.get(user_id)

    if user and user.role and user.role.code == "SUPER_USUARIO":
        return

    allowed_ids = _get_user_accessible_warehouse_ids(user_id)
    if warehouse_id not in allowed_ids:
        raise TransferServiceError("El usuario no tiene acceso a la bodega seleccionada.")


def _get_warehouse(warehouse_id: int) -> Warehouse:
    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        raise TransferServiceError("La bodega no existe.")
    if not warehouse.is_active:
        raise TransferServiceError("La bodega seleccionada está inactiva.")
    return warehouse


def _get_article(article_id: int) -> Article:
    article = Article.query.get(article_id)
    if not article:
        raise TransferServiceError("El artículo no existe.")
    return article


def _get_or_create_stock(warehouse_id: int, article_id: int) -> WarehouseStock:
    stock = (
        WarehouseStock.query
        .filter_by(warehouse_id=warehouse_id, article_id=article_id)
        .first()
    )
    if stock:
        return stock

    stock = WarehouseStock(
        warehouse_id=warehouse_id,
        article_id=article_id,
        quantity_on_hand=Decimal("0"),
        reserved_quantity=Decimal("0"),
    )
    db.session.add(stock)
    db.session.flush()
    return stock


def _get_available_quantity(warehouse_id: int, article_id: int) -> Decimal:
    stock = (
        WarehouseStock.query
        .filter_by(warehouse_id=warehouse_id, article_id=article_id)
        .first()
    )
    if not stock:
        return Decimal("0")
    return Decimal(str(stock.available_quantity or 0))


def _recalculate_request_status(request_obj: TransferRequest) -> str:
    lines = list(
        TransferRequestLine.query
        .filter_by(transfer_request_id=request_obj.id)
        .all()
    )

    if not lines:
        return REQUEST_STATUS_BORRADOR

    approved_lines = []
    rejected_lines = []
    attended_total = Decimal("0")
    approved_total = Decimal("0")
    any_partial = False

    for line in lines:
        review_status = (line.manager_review_status or REQUEST_LINE_REVIEW_PENDIENTE).strip().upper()
        line_status = (line.line_status or REQUEST_LINE_STATUS_SOLICITADA).strip().upper()
        qty_approved = Decimal(str(line.quantity_approved or 0))
        qty_attended = Decimal(str(line.quantity_attended or 0))

        if review_status == REQUEST_LINE_REVIEW_APROBADA:
            approved_lines.append(line)
            approved_total += qty_approved
            attended_total += qty_attended
            if line_status == REQUEST_LINE_STATUS_ATENDIDA_PARCIAL:
                any_partial = True

        elif review_status == REQUEST_LINE_REVIEW_RECHAZADA:
            rejected_lines.append(line)

    if approved_lines:
        if approved_total > 0 and attended_total >= approved_total:
            return REQUEST_STATUS_ATENDIDA

        if attended_total > 0 or any_partial:
            return REQUEST_STATUS_ATENDIDA_PARCIAL

        return REQUEST_STATUS_APROBADA

    if rejected_lines and len(rejected_lines) == len(lines):
        return REQUEST_STATUS_RECHAZADA

    return REQUEST_STATUS_ENVIADA


def get_request_line_stock_context(
    *,
    requesting_warehouse_id: int,
    supplying_warehouse_id: int,
    article_id: int,
) -> dict:
    """
    Esto es solo apoyo visual para la solicitud y jefatura.
    No persiste stock en la solicitud.
    """
    return {
        "requesting_available_quantity": _get_available_quantity(requesting_warehouse_id, article_id),
        "supplying_available_quantity": _get_available_quantity(supplying_warehouse_id, article_id),
    }


def create_transfer_request(
    *,
    requested_by_user_id: int,
    origin_warehouse_id: int,
    destination_warehouse_id: int,
    priority: str = "NORMAL",
    notes: str | None = None,
    number: str | None = None,
    commit: bool = True,
) -> TransferRequest:
    _validate_user_warehouse_access(requested_by_user_id, origin_warehouse_id)

    origin_warehouse = _get_warehouse(origin_warehouse_id)
    destination_warehouse = _get_warehouse(destination_warehouse_id)

    if origin_warehouse.id == destination_warehouse.id:
        raise TransferServiceError("La bodega origen y destino no pueden ser la misma.")

    request_obj = TransferRequest(
        number=number or _build_number("STR"),
        requested_by_user_id=requested_by_user_id,
        origin_site_id=origin_warehouse.site_id,
        origin_warehouse_id=origin_warehouse.id,
        destination_site_id=destination_warehouse.site_id,
        destination_warehouse_id=destination_warehouse.id,
        priority=(priority or "NORMAL").strip().upper(),
        status=REQUEST_STATUS_BORRADOR,
        notes=(notes or "").strip() or None,
        created_at=_now(),
    )

    db.session.add(request_obj)
    db.session.flush()

    log_action(
        user_id=requested_by_user_id,
        action="CREATE_TRANSFER_REQUEST",
        table_name="transfer_requests",
        record_id=str(request_obj.id),
        details={
            "number": request_obj.number,
            "origin_warehouse_id": origin_warehouse.id,
            "destination_warehouse_id": destination_warehouse.id,
            "priority": request_obj.priority,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return request_obj


def add_transfer_request_line(
    *,
    transfer_request_id: int,
    article_id: int,
    quantity_requested,
    notes: str | None = None,
    performed_by_user_id: int,
    commit: bool = True,
) -> TransferRequestLine:
    request_obj = TransferRequest.query.get(transfer_request_id)
    if not request_obj:
        raise TransferServiceError("La solicitud de traslado no existe.")

    if request_obj.status not in {REQUEST_STATUS_BORRADOR, REQUEST_STATUS_ENVIADA}:
        raise TransferServiceError("No se pueden agregar líneas en el estado actual de la solicitud.")

    _validate_user_warehouse_access(performed_by_user_id, request_obj.origin_warehouse_id)
    _get_article(article_id)
    qty = _to_decimal(quantity_requested, field_name="cantidad solicitada")

    line = TransferRequestLine(
        transfer_request_id=request_obj.id,
        article_id=article_id,
        quantity_requested=qty,
        quantity_approved=None,
        quantity_attended=Decimal("0"),
        manager_review_status=REQUEST_LINE_REVIEW_PENDIENTE,
        manager_reviewed_by_user_id=None,
        manager_reviewed_at=None,
        line_status=REQUEST_LINE_STATUS_SOLICITADA,
        not_delivered_reason=None,
        notes=(notes or "").strip() or None,
        created_at=_now(),
    )

    db.session.add(line)
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="ADD_TRANSFER_REQUEST_LINE",
        table_name="transfer_request_lines",
        record_id=str(line.id),
        details={
            "transfer_request_id": request_obj.id,
            "article_id": article_id,
            "quantity_requested": str(qty),
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return line


def update_transfer_request_line_quantity(
    *,
    transfer_request_line_id: int,
    quantity_requested,
    performed_by_user_id: int,
    commit: bool = True,
) -> TransferRequestLine:
    line = TransferRequestLine.query.get(transfer_request_line_id)
    if not line:
        raise TransferServiceError("La línea de solicitud no existe.")

    request_obj = line.transfer_request
    if request_obj.status not in {REQUEST_STATUS_BORRADOR, REQUEST_STATUS_ENVIADA}:
        raise TransferServiceError("No se puede modificar la línea en el estado actual.")

    if (line.manager_review_status or REQUEST_LINE_REVIEW_PENDIENTE) != REQUEST_LINE_REVIEW_PENDIENTE:
        raise TransferServiceError("No se puede modificar una línea ya revisada por jefatura.")

    qty = _to_decimal(quantity_requested, field_name="cantidad solicitada")
    line.quantity_requested = qty
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="UPDATE_TRANSFER_REQUEST_LINE_QUANTITY",
        table_name="transfer_request_lines",
        record_id=str(line.id),
        details={
            "transfer_request_id": request_obj.id,
            "new_quantity_requested": str(qty),
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return line


def remove_transfer_request_line(
    *,
    transfer_request_line_id: int,
    performed_by_user_id: int,
    commit: bool = True,
) -> None:
    line = TransferRequestLine.query.get(transfer_request_line_id)
    if not line:
        raise TransferServiceError("La línea de solicitud no existe.")

    request_obj = line.transfer_request
    if request_obj.status not in {REQUEST_STATUS_BORRADOR, REQUEST_STATUS_ENVIADA}:
        raise TransferServiceError("No se puede eliminar la línea en el estado actual.")

    if (line.manager_review_status or REQUEST_LINE_REVIEW_PENDIENTE) != REQUEST_LINE_REVIEW_PENDIENTE:
        raise TransferServiceError("No se puede eliminar una línea ya revisada por jefatura.")

    log_action(
        user_id=performed_by_user_id,
        action="REMOVE_TRANSFER_REQUEST_LINE",
        table_name="transfer_request_lines",
        record_id=str(line.id),
        details={
            "transfer_request_id": request_obj.id,
            "article_id": line.article_id,
            "quantity_requested": str(line.quantity_requested),
        },
        commit=False,
    )

    db.session.delete(line)
    db.session.flush()

    if commit:
        db.session.commit()


def send_transfer_request(
    *,
    transfer_request_id: int,
    performed_by_user_id: int,
    commit: bool = True,
) -> TransferRequest:
    request_obj = TransferRequest.query.get(transfer_request_id)
    if not request_obj:
        raise TransferServiceError("La solicitud de traslado no existe.")

    if request_obj.status != REQUEST_STATUS_BORRADOR:
        raise TransferServiceError("Solo se pueden enviar solicitudes en borrador.")

    lines_count = (
        TransferRequestLine.query
        .filter_by(transfer_request_id=request_obj.id)
        .count()
    )
    if lines_count == 0:
        raise TransferServiceError("No se puede enviar una solicitud sin líneas.")

    request_obj.status = REQUEST_STATUS_ENVIADA
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="SEND_TRANSFER_REQUEST",
        table_name="transfer_requests",
        record_id=str(request_obj.id),
        details={"status": request_obj.status},
        commit=False,
    )

    if commit:
        db.session.commit()

    return request_obj


def review_transfer_request_line(
    *,
    transfer_request_line_id: int,
    performed_by_user_id: int,
    action: str,
    quantity_approved=None,
    rejection_reason: str | None = None,
    commit: bool = True,
) -> TransferRequestLine:
    line = TransferRequestLine.query.get(transfer_request_line_id)
    if not line:
        raise TransferServiceError("La línea de solicitud no existe.")

    request_obj = line.transfer_request
    if request_obj.status != REQUEST_STATUS_ENVIADA:
        raise TransferServiceError("Solo se pueden revisar líneas en solicitudes enviadas.")

    normalized_action = (action or "").strip().upper()
    if normalized_action not in {"APROBAR", "RECHAZAR"}:
        raise TransferServiceError("Acción inválida.")

    if normalized_action == "APROBAR":
        qty = _to_decimal(
            quantity_approved if quantity_approved is not None else line.quantity_requested,
            field_name="cantidad aprobada",
        )

        requested_qty = Decimal(str(line.quantity_requested or 0))
        if qty > requested_qty:
            raise TransferServiceError("No se puede aprobar más de lo solicitado.")

        line.quantity_approved = qty
        line.manager_review_status = REQUEST_LINE_REVIEW_APROBADA
        line.line_status = REQUEST_LINE_STATUS_APROBADA
        line.not_delivered_reason = None

    else:
        line.quantity_approved = Decimal("0")
        line.manager_review_status = REQUEST_LINE_REVIEW_RECHAZADA
        line.line_status = REQUEST_LINE_STATUS_CANCELADA
        line.not_delivered_reason = (rejection_reason or "").strip() or None

    line.manager_reviewed_by_user_id = performed_by_user_id
    line.manager_reviewed_at = _now()

    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="REVIEW_TRANSFER_REQUEST_LINE",
        table_name="transfer_request_lines",
        record_id=str(line.id),
        details={
            "transfer_request_id": request_obj.id,
            "action": normalized_action,
            "quantity_approved": str(line.quantity_approved or 0),
            "line_status": line.line_status,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return line


def finalize_transfer_request_review(
    *,
    transfer_request_id: int,
    performed_by_user_id: int,
    approval_note: str | None = None,
    commit: bool = True,
) -> TransferRequest:
    request_obj = TransferRequest.query.get(transfer_request_id)
    if not request_obj:
        raise TransferServiceError("La solicitud de traslado no existe.")

    if request_obj.status != REQUEST_STATUS_ENVIADA:
        raise TransferServiceError("La solicitud no está en estado válido para revisión.")

    lines = list(
        TransferRequestLine.query
        .filter_by(transfer_request_id=request_obj.id)
        .all()
    )

    if not lines:
        raise TransferServiceError("La solicitud no tiene líneas.")

    pending_lines = [
        line for line in lines
        if (line.manager_review_status or REQUEST_LINE_REVIEW_PENDIENTE) == REQUEST_LINE_REVIEW_PENDIENTE
    ]
    if pending_lines:
        raise TransferServiceError("No se puede finalizar la revisión mientras existan líneas pendientes.")

    approved_lines = [
        line for line in lines
        if (line.manager_review_status or "").strip().upper() == REQUEST_LINE_REVIEW_APROBADA
    ]
    rejected_lines = [
        line for line in lines
        if (line.manager_review_status or "").strip().upper() == REQUEST_LINE_REVIEW_RECHAZADA
    ]

    if not approved_lines and rejected_lines:
        request_obj.status = REQUEST_STATUS_RECHAZADA
    else:
        request_obj.status = REQUEST_STATUS_APROBADA

    request_obj.approved_by_user_id = performed_by_user_id
    request_obj.approved_at = _now()

    if approval_note:
        request_obj.notes = _append_note(
            request_obj.notes,
            f"[REVISION_JEFATURA {_now().isoformat()}] {approval_note.strip()}",
        )

    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="FINALIZE_TRANSFER_REQUEST_REVIEW",
        table_name="transfer_requests",
        record_id=str(request_obj.id),
        details={"status": request_obj.status},
        commit=False,
    )

    if commit:
        db.session.commit()

    return request_obj


def send_transfer_request_to_warehouse(
    *,
    transfer_request_id: int,
    performed_by_user_id: int,
    commit: bool = True,
) -> TransferRequest:
    request_obj = TransferRequest.query.get(transfer_request_id)
    if not request_obj:
        raise TransferServiceError("La solicitud no existe.")

    if request_obj.status != REQUEST_STATUS_APROBADA:
        raise TransferServiceError("Solo las solicitudes aprobadas pueden enviarse a bodega.")

    approved_lines = (
        TransferRequestLine.query
        .filter(
            TransferRequestLine.transfer_request_id == request_obj.id,
            TransferRequestLine.manager_review_status == REQUEST_LINE_REVIEW_APROBADA,
        )
        .count()
    )
    if approved_lines == 0:
        raise TransferServiceError("La solicitud no tiene líneas aprobadas para enviar a bodega.")

    request_obj.sent_to_warehouse_by_user_id = performed_by_user_id
    request_obj.sent_to_warehouse_at = _now()

    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="SEND_TRANSFER_REQUEST_TO_WAREHOUSE",
        table_name="transfer_requests",
        record_id=str(request_obj.id),
        details={
            "status": request_obj.status,
            "sent_to_warehouse_at": request_obj.sent_to_warehouse_at.isoformat() if request_obj.sent_to_warehouse_at else None,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return request_obj


def approve_transfer_request(
    *,
    transfer_request_id: int,
    performed_by_user_id: int,
    approval_note: str | None = None,
    commit: bool = True,
) -> TransferRequest:
    """
    Se mantiene por compatibilidad, pero ahora finaliza la revisión por línea.
    """
    return finalize_transfer_request_review(
        transfer_request_id=transfer_request_id,
        performed_by_user_id=performed_by_user_id,
        approval_note=approval_note,
        commit=commit,
    )


def reject_transfer_request(
    *,
    transfer_request_id: int,
    performed_by_user_id: int,
    rejection_reason: str | None = None,
    commit: bool = True,
) -> TransferRequest:
    request_obj = TransferRequest.query.get(transfer_request_id)
    if not request_obj:
        raise TransferServiceError("La solicitud de traslado no existe.")

    if request_obj.status not in {
        REQUEST_STATUS_BORRADOR,
        REQUEST_STATUS_ENVIADA,
        REQUEST_STATUS_APROBADA,
    }:
        raise TransferServiceError("La solicitud no puede rechazarse en el estado actual.")

    request_obj.status = REQUEST_STATUS_RECHAZADA
    request_obj.notes = _append_note(
        request_obj.notes,
        f"[RECHAZADA {_now().isoformat()}] {(rejection_reason or '').strip()}".strip()
    )

    if request_obj.status == REQUEST_STATUS_ENVIADA:
        lines = (
            TransferRequestLine.query
            .filter_by(transfer_request_id=request_obj.id)
            .all()
        )
        for line in lines:
            line.quantity_approved = Decimal("0")
            line.manager_review_status = REQUEST_LINE_REVIEW_RECHAZADA
            line.manager_reviewed_by_user_id = performed_by_user_id
            line.manager_reviewed_at = _now()
            line.line_status = REQUEST_LINE_STATUS_CANCELADA
            line.not_delivered_reason = (rejection_reason or "").strip() or None

    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="REJECT_TRANSFER_REQUEST",
        table_name="transfer_requests",
        record_id=str(request_obj.id),
        details={"status": request_obj.status},
        commit=False,
    )

    if commit:
        db.session.commit()

    return request_obj


def create_transfer_draft_from_request(
    *,
    transfer_request_id: int,
    created_by_user_id: int,
    selected_lines: list[dict],
    notes: str | None = None,
    number: str | None = None,
    commit: bool = True,
) -> Transfer:
    """
    selected_lines esperado:
    [
        {"transfer_request_line_id": 1, "quantity_sent": 5},
        ...
    ]

    OJO:
    - la solicitud nace desde la bodega que pide
    - el traslado real sale desde la bodega abastecedora
    Por eso aquí se invierten origen/destino respecto a transfer_requests.
    """
    request_obj = TransferRequest.query.get(transfer_request_id)
    if not request_obj:
        raise TransferServiceError("La solicitud de traslado no existe.")

    if request_obj.status not in {REQUEST_STATUS_APROBADA, REQUEST_STATUS_ATENDIDA_PARCIAL}:
        raise TransferServiceError("Solo se puede crear traslado desde solicitudes aprobadas o parcialmente atendidas.")

    if not request_obj.sent_to_warehouse_at:
        raise TransferServiceError("La solicitud aún no ha sido enviada a bodega.")

    if not selected_lines:
        raise TransferServiceError("Debe seleccionar al menos una línea para el traslado.")

    supplying_warehouse = _get_warehouse(request_obj.destination_warehouse_id)
    requesting_warehouse = _get_warehouse(request_obj.origin_warehouse_id)

    transfer = Transfer(
        number=number or _build_number("TRS"),
        created_from_request_id=request_obj.id,
        created_by_user_id=created_by_user_id,
        origin_site_id=supplying_warehouse.site_id,
        origin_warehouse_id=supplying_warehouse.id,
        destination_site_id=requesting_warehouse.site_id,
        destination_warehouse_id=requesting_warehouse.id,
        status=TRANSFER_STATUS_BORRADOR,
        notes=(notes or "").strip() or None,
        created_at=_now(),
    )

    db.session.add(transfer)
    db.session.flush()

    request_lines = {
        line.id: line
        for line in TransferRequestLine.query.filter_by(transfer_request_id=request_obj.id).all()
    }

    has_partial = False

    for selected in selected_lines:
        line_id = selected.get("transfer_request_line_id")
        qty = _to_decimal(selected.get("quantity_sent"), field_name="cantidad a trasladar")

        request_line = request_lines.get(line_id)
        if not request_line:
            raise TransferServiceError("Una de las líneas seleccionadas no pertenece a la solicitud.")

        if (request_line.manager_review_status or "").strip().upper() != REQUEST_LINE_REVIEW_APROBADA:
            raise TransferServiceError("Solo se pueden trasladar líneas aprobadas.")

        approved_qty = Decimal(str(request_line.quantity_approved or 0))
        attended_qty = Decimal(str(request_line.quantity_attended or 0))
        remaining_qty = approved_qty - attended_qty

        if approved_qty <= 0:
            raise TransferServiceError("La línea no está aprobada para traslado.")

        if remaining_qty <= 0:
            raise TransferServiceError("La línea ya fue atendida completamente.")

        if qty > remaining_qty:
            raise TransferServiceError("No puede trasladar más de lo aprobado pendiente por atender.")

        new_attended_qty = attended_qty + qty
        request_line.quantity_attended = new_attended_qty

        if new_attended_qty < approved_qty:
            has_partial = True
            request_line.line_status = REQUEST_LINE_STATUS_ATENDIDA_PARCIAL
        else:
            request_line.line_status = REQUEST_LINE_STATUS_ATENDIDA

        transfer_line = TransferLine(
            transfer_id=transfer.id,
            article_id=request_line.article_id,
            quantity_sent=qty,
            quantity_received=None,
            line_status=TRANSFER_LINE_STATUS_BORRADOR,
            notes=request_line.notes,
            created_at=_now(),
        )
        db.session.add(transfer_line)

    request_obj.status = _recalculate_request_status(request_obj)

    event = TransferEvent(
        transfer_id=transfer.id,
        event_type="CREADO_BORRADOR",
        event_message="Traslado creado en borrador desde solicitud aprobada.",
        performed_by_user_id=created_by_user_id,
        created_at=_now(),
    )
    db.session.add(event)
    db.session.flush()

    log_action(
        user_id=created_by_user_id,
        action="CREATE_TRANSFER_DRAFT_FROM_REQUEST",
        table_name="transfers",
        record_id=str(transfer.id),
        details={
            "number": transfer.number,
            "created_from_request_id": request_obj.id,
            "origin_warehouse_id": transfer.origin_warehouse_id,
            "destination_warehouse_id": transfer.destination_warehouse_id,
            "status": transfer.status,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return transfer


def add_or_update_transfer_line_in_draft(
    *,
    transfer_id: int,
    article_id: int,
    quantity_sent,
    performed_by_user_id: int,
    notes: str | None = None,
    commit: bool = True,
) -> TransferLine:
    transfer = Transfer.query.get(transfer_id)
    if not transfer:
        raise TransferServiceError("El traslado no existe.")

    if transfer.status != TRANSFER_STATUS_BORRADOR:
        raise TransferServiceError("Solo se pueden ajustar líneas en traslados borrador.")

    qty = _to_decimal(quantity_sent, field_name="cantidad a trasladar")
    available = _get_available_quantity(transfer.origin_warehouse_id, article_id)
    if qty > available:
        raise TransferServiceError("No hay stock suficiente para esa cantidad en la bodega origen.")

    line = (
        TransferLine.query
        .filter_by(transfer_id=transfer.id, article_id=article_id)
        .first()
    )

    if line:
        line.quantity_sent = qty
        line.notes = _append_note(line.notes, notes)
    else:
        line = TransferLine(
            transfer_id=transfer.id,
            article_id=article_id,
            quantity_sent=qty,
            quantity_received=None,
            line_status=TRANSFER_LINE_STATUS_BORRADOR,
            notes=(notes or "").strip() or None,
            created_at=_now(),
        )
        db.session.add(line)

    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="UPSERT_TRANSFER_LINE_IN_DRAFT",
        table_name="transfer_lines",
        record_id=str(line.id),
        details={
            "transfer_id": transfer.id,
            "article_id": article_id,
            "quantity_sent": str(qty),
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return line


def send_transfer(
    *,
    transfer_id: int,
    performed_by_user_id: int,
    commit: bool = True,
) -> Transfer:
    transfer = Transfer.query.get(transfer_id)
    if not transfer:
        raise TransferServiceError("El traslado no existe.")

    if transfer.status != TRANSFER_STATUS_BORRADOR:
        raise TransferServiceError("Solo se pueden enviar traslados en borrador.")

    lines = list(transfer.lines)
    if not lines:
        raise TransferServiceError("El traslado no tiene líneas para enviar.")

    for line in lines:
        qty = Decimal(str(line.quantity_sent or 0))
        if qty <= 0:
            raise TransferServiceError("Una línea del traslado no tiene cantidad válida.")

        stock = _get_or_create_stock(transfer.origin_warehouse_id, line.article_id)
        available = Decimal(str(stock.available_quantity or 0))

        if qty > available:
            raise TransferServiceError(
                f"No hay stock suficiente en origen para el artículo {line.article.code if line.article else line.article_id}."
            )

        unit_cost = None
        if stock.avg_unit_cost is not None:
            unit_cost = Decimal(str(stock.avg_unit_cost))
        elif stock.last_unit_cost is not None:
            unit_cost = Decimal(str(stock.last_unit_cost))

        stock.quantity_on_hand = Decimal(str(stock.quantity_on_hand or 0)) - qty

        ledger = InventoryLedger(
            movement_type="TRASLADO_SALIDA",
            warehouse_id=transfer.origin_warehouse_id,
            related_warehouse_id=transfer.destination_warehouse_id,
            warehouse_location_id=None,
            article_id=line.article_id,
            quantity_change=(qty * Decimal("-1")),
            unit_cost=unit_cost,
            total_cost=(qty * unit_cost) if unit_cost is not None else None,
            reference_type="TRANSFER",
            reference_id=transfer.id,
            reference_number=transfer.number,
            notes=f"Salida por traslado {transfer.number}",
            performed_by_user_id=performed_by_user_id,
            created_at=_now(),
        )
        db.session.add(ledger)

        line.line_status = TRANSFER_LINE_STATUS_EN_TRANSITO

    transfer.status = TRANSFER_STATUS_EN_TRANSITO
    transfer.sent_at = _now()

    event = TransferEvent(
        transfer_id=transfer.id,
        event_type="ENVIADO",
        event_message="Traslado enviado a bodega destino.",
        performed_by_user_id=performed_by_user_id,
        created_at=_now(),
    )
    db.session.add(event)

    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="SEND_TRANSFER",
        table_name="transfers",
        record_id=str(transfer.id),
        details={
            "status": transfer.status,
            "sent_at": transfer.sent_at.isoformat() if transfer.sent_at else None,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return transfer


def receive_transfer(
    *,
    transfer_id: int,
    received_by_user_id: int,
    received_lines: list[dict] | None = None,
    commit: bool = True,
) -> Transfer:
    """
    received_lines opcional:
    [
        {"transfer_line_id": 1, "quantity_received": 5},
        ...
    ]

    Si no se envía, se recibe exactamente lo enviado.
    """
    transfer = Transfer.query.get(transfer_id)
    if not transfer:
        raise TransferServiceError("El traslado no existe.")

    if transfer.status != TRANSFER_STATUS_EN_TRANSITO:
        raise TransferServiceError("Solo se pueden recibir traslados en tránsito.")

    lines = list(transfer.lines)
    if not lines:
        raise TransferServiceError("El traslado no tiene líneas.")

    received_map = {}
    if received_lines:
        for item in received_lines:
            received_map[int(item["transfer_line_id"])] = _to_decimal(
                item["quantity_received"],
                field_name="cantidad recibida",
            )

    for line in lines:
        qty_sent = Decimal(str(line.quantity_sent or 0))
        qty_received = received_map.get(line.id, qty_sent)

        if qty_received <= 0:
            raise TransferServiceError("La cantidad recibida debe ser mayor a 0.")

        if qty_received > qty_sent:
            raise TransferServiceError("No se puede recibir más de lo enviado.")

        origin_stock = _get_or_create_stock(transfer.origin_warehouse_id, line.article_id)
        destination_stock = _get_or_create_stock(transfer.destination_warehouse_id, line.article_id)

        unit_cost = None
        if origin_stock.avg_unit_cost is not None:
            unit_cost = Decimal(str(origin_stock.avg_unit_cost))
        elif origin_stock.last_unit_cost is not None:
            unit_cost = Decimal(str(origin_stock.last_unit_cost))
        elif destination_stock.avg_unit_cost is not None:
            unit_cost = Decimal(str(destination_stock.avg_unit_cost))
        elif destination_stock.last_unit_cost is not None:
            unit_cost = Decimal(str(destination_stock.last_unit_cost))

        current_dest_qty = Decimal(str(destination_stock.quantity_on_hand or 0))
        destination_stock.quantity_on_hand = current_dest_qty + qty_received

        if unit_cost is not None:
            previous_avg = Decimal(str(destination_stock.avg_unit_cost or 0))
            if current_dest_qty <= 0:
                destination_stock.avg_unit_cost = unit_cost
            else:
                destination_stock.avg_unit_cost = (
                    ((current_dest_qty * previous_avg) + (qty_received * unit_cost))
                    / (current_dest_qty + qty_received)
                )
            destination_stock.last_unit_cost = unit_cost

        ledger = InventoryLedger(
            movement_type="TRASLADO_ENTRADA",
            warehouse_id=transfer.destination_warehouse_id,
            related_warehouse_id=transfer.origin_warehouse_id,
            warehouse_location_id=None,
            article_id=line.article_id,
            quantity_change=qty_received,
            unit_cost=unit_cost,
            total_cost=(qty_received * unit_cost) if unit_cost is not None else None,
            reference_type="TRANSFER",
            reference_id=transfer.id,
            reference_number=transfer.number,
            notes=f"Entrada por traslado {transfer.number}",
            performed_by_user_id=received_by_user_id,
            created_at=_now(),
        )
        db.session.add(ledger)

        line.quantity_received = qty_received
        line.line_status = TRANSFER_LINE_STATUS_RECIBIDA

    transfer.status = TRANSFER_STATUS_RECIBIDO
    transfer.received_at = _now()
    transfer.received_by_user_id = received_by_user_id

    event = TransferEvent(
        transfer_id=transfer.id,
        event_type="RECIBIDO",
        event_message="Traslado recibido en bodega destino.",
        performed_by_user_id=received_by_user_id,
        created_at=_now(),
    )
    db.session.add(event)

    db.session.flush()

    log_action(
        user_id=received_by_user_id,
        action="RECEIVE_TRANSFER",
        table_name="transfers",
        record_id=str(transfer.id),
        details={
            "status": transfer.status,
            "received_at": transfer.received_at.isoformat() if transfer.received_at else None,
            "received_by_user_id": received_by_user_id,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return transfer