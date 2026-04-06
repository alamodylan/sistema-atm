from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func

from app.extensions import db
from app.models.article import Article
from app.models.pending_article import PendingArticle
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


def _generate_provisional_article_code() -> str:
    """
    Formato:
    PEND-000001
    """
    last_pending_code = (
        db.session.query(Article.code)
        .filter(Article.code.ilike("PEND-%"))
        .order_by(Article.id.desc())
        .first()
    )

    if not last_pending_code or not last_pending_code[0]:
        next_number = 1
    else:
        raw_code = str(last_pending_code[0]).strip().upper()
        try:
            next_number = int(raw_code.replace("PEND-", "")) + 1
        except Exception:
            next_number = 1

    while True:
        candidate = f"PEND-{next_number:06d}"
        exists = Article.query.filter_by(code=candidate).first()
        if not exists:
            return candidate
        next_number += 1


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

    if not line.unit_id:
        raise PurchaseRequestServiceError(
            "Cada línea debe indicar una unidad."
        )


def _ensure_pending_article_has_real_article(
    *,
    pending_article_id: int,
    requested_by_user_id: int,
    fallback_unit_id: int | None,
) -> PendingArticle:
    pending_article = PendingArticle.query.get(pending_article_id)
    if not pending_article:
        raise PurchaseRequestServiceError(
            "El artículo pendiente indicado no existe."
        )

    if pending_article.linked_article_id:
        return pending_article

    resolved_unit_id = pending_article.unit_id or fallback_unit_id
    if not resolved_unit_id:
        raise PurchaseRequestServiceError(
            "El artículo pendiente no tiene unidad definida y la línea tampoco indica una unidad."
        )

    provisional_name = (
        (getattr(pending_article, "provisional_name", None) or "").strip()
        or "ARTÍCULO PENDIENTE"
    )

    article = Article(
        code=_generate_provisional_article_code(),
        name=provisional_name,
        description=(getattr(pending_article, "notes", None) or "").strip() or None,
        category_id=None,
        unit_id=resolved_unit_id,
        family_code=None,
        barcode=None,
        sap_code=None,
        is_tool=False,
        is_active=True,
        created_by_user_id=requested_by_user_id,
    )
    db.session.add(article)
    db.session.flush()

    pending_article.linked_article_id = article.id

    return pending_article


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
        normalized_quantity = _normalize_decimal(line.quantity_requested)

        if line.pending_article_id:
            _ensure_pending_article_has_real_article(
                pending_article_id=line.pending_article_id,
                requested_by_user_id=requested_by_user_id,
                fallback_unit_id=line.unit_id,
            )

        purchase_request_line = PurchaseRequestLine(
            purchase_request_id=purchase_request.id,
            article_id=line.article_id,
            pending_article_id=line.pending_article_id,
            quantity_requested=normalized_quantity,
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