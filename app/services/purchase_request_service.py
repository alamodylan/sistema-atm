from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func

from app.extensions import db
from app.models.purchase_request import PurchaseRequest
from app.models.purchase_request_line import PurchaseRequestLine


class PurchaseRequestServiceError(Exception):
    pass


@dataclass
class PurchaseRequestLinePayload:
    article_id: int | None
    pending_article_id: int | None
    quantity_requested: Decimal
    unit_id: int | None
    line_notes: str | None = None
    is_urgent: bool = False


def _normalize_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise PurchaseRequestServiceError("Cantidad inválida.") from exc


def _generate_purchase_request_number() -> str:
    """
    Formato sugerido:
    SC-000001
    """
    max_id = db.session.query(func.max(PurchaseRequest.id)).scalar() or 0
    next_id = int(max_id) + 1
    return f"SC-{next_id:06d}"


def _validate_line_payload(line: PurchaseRequestLinePayload) -> None:
    if bool(line.article_id) == bool(line.pending_article_id):
        raise PurchaseRequestServiceError(
            "Cada línea debe tener un artículo normal o un artículo pendiente, pero no ambos."
        )

    qty = _normalize_decimal(line.quantity_requested)
    if qty <= 0:
        raise PurchaseRequestServiceError(
            "La cantidad solicitada debe ser mayor que cero."
        )


def create_purchase_request(
    *,
    requested_by_user_id: int,
    priority: str,
    notes: str | None,
    site_id: int | None,
    warehouse_id: int | None,
    lines: list[PurchaseRequestLinePayload],
) -> PurchaseRequest:
    if not lines:
        raise PurchaseRequestServiceError(
            "La solicitud debe incluir al menos una línea."
        )

    valid_priorities = {"NORMAL", "URGENTE", "CRITICA"}
    if priority not in valid_priorities:
        raise PurchaseRequestServiceError("Prioridad inválida.")

    for line in lines:
        _validate_line_payload(line)

    purchase_request = PurchaseRequest(
        number=_generate_purchase_request_number(),
        requested_by_user_id=requested_by_user_id,
        priority=priority,
        status="BORRADOR",
        notes=(notes or "").strip() or None,
        site_id=site_id,
        warehouse_id=warehouse_id,
    )

    db.session.add(purchase_request)
    db.session.flush()

    for line in lines:
        purchase_request_line = PurchaseRequestLine(
            purchase_request_id=purchase_request.id,
            article_id=line.article_id,
            pending_article_id=line.pending_article_id,
            quantity_requested=_normalize_decimal(line.quantity_requested),
            unit_id=line.unit_id,
            line_notes=(line.line_notes or "").strip() or None,
            is_urgent=bool(line.is_urgent),
            line_status="ACTIVA",
        )
        db.session.add(purchase_request_line)

    db.session.commit()
    return purchase_request


def get_purchase_request_or_404(request_id: int) -> PurchaseRequest:
    purchase_request = PurchaseRequest.query.get_or_404(request_id)
    return purchase_request


def list_purchase_requests(
    *,
    status: str | None = None,
    priority: str | None = None,
    search: str | None = None,
) -> list[PurchaseRequest]:
    query = PurchaseRequest.query

    if status:
        query = query.filter(PurchaseRequest.status == status)

    if priority:
        query = query.filter(PurchaseRequest.priority == priority)

    if search:
        like_value = f"%{search.strip()}%"
        query = query.filter(
            PurchaseRequest.number.ilike(like_value)
        )

    return (
        query.order_by(PurchaseRequest.created_at.desc(), PurchaseRequest.id.desc())
        .all()
    )