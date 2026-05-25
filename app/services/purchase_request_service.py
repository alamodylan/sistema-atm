from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from datetime import UTC, datetime

from sqlalchemy import func

from app.extensions import db
from app.models.article import Article
from app.models.pending_article import PendingArticle
from app.models.purchase_request import PurchaseRequest
from app.models.purchase_request_line import PurchaseRequestLine
from app.services.request_routing_service import resolve_request_routing
from sqlalchemy.orm import joinedload


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

    purchase_request = (
        PurchaseRequest.query
        .options(

            # =================================================
            # ENCABEZADO
            # =================================================

            joinedload(PurchaseRequest.requested_by_user),

            joinedload(PurchaseRequest.site),

            joinedload(PurchaseRequest.warehouse),

            # =================================================
            # LÍNEAS
            # =================================================

            joinedload(PurchaseRequest.lines)
            .joinedload(PurchaseRequestLine.unit),

            # =================================================
            # COTIZACIONES
            # =================================================

            joinedload(PurchaseRequest.quotation_batches),

            # =================================================
            # OC
            # =================================================

            joinedload(PurchaseRequest.purchase_orders),

        )
        .filter(
            PurchaseRequest.id == request_id
        )
        .first_or_404()
    )

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

def submit_purchase_request(*, request_id: int) -> PurchaseRequest:

    purchase_request = PurchaseRequest.query.get(request_id)

    if not purchase_request:
        raise PurchaseRequestServiceError(
            "La solicitud indicada no existe."
        )

    if purchase_request.status != "BORRADOR":
        raise PurchaseRequestServiceError(
            "Solo se pueden enviar solicitudes en borrador."
        )

    active_lines = [
        line for line in purchase_request.lines
        if line.line_status != "CANCELADA"
    ]

    if not active_lines:
        raise PurchaseRequestServiceError(
            "La solicitud no tiene líneas activas."
        )

    # =====================================================
    # ROUTING CONFIGURABLE
    # =====================================================

    review_site_id = purchase_request.site_id

    sent_direct_to_procurement = False

    routing = resolve_request_routing(
        origin_site_id=purchase_request.site_id,
        request_type="PURCHASE_REQUEST",
    )

    if routing.get("has_rule"):

        routing_mode = routing.get("routing_mode")

        # =================================================
        # MISMO DASHBOARD JEFATURA
        # =================================================

        if routing_mode == "LOCAL_MANAGER_DASHBOARD":

            review_site_id = purchase_request.site_id

            purchase_request.status = "ENVIADA"

        # =================================================
        # OTRO DASHBOARD JEFATURA
        # =================================================

        elif routing_mode == "OTHER_SITE_MANAGER_DASHBOARD":

            review_site_id = (
                routing.get("target_site_id")
                or purchase_request.site_id
            )

            purchase_request.status = "ENVIADA"

        # =================================================
        # DIRECTO A PROVEEDURÍA
        # =================================================

        elif routing_mode == "DIRECT_TO_PROCUREMENT":

            review_site_id = None

            sent_direct_to_procurement = True

            purchase_request.status = "EN_REVISION_PROVEEDURIA"

            now = datetime.now(UTC)

            for line in active_lines:
                line.line_status = "ENVIADA_A_COTIZAR"
                line.sent_to_quote_at = now

        # =================================================
        # FALLBACK
        # =================================================

        else:

            purchase_request.status = "ENVIADA"

            review_site_id = purchase_request.site_id

    else:

        # =================================================
        # COMPORTAMIENTO ACTUAL
        # =================================================

        purchase_request.status = "ENVIADA"

        review_site_id = purchase_request.site_id

    purchase_request.review_site_id = review_site_id

    purchase_request.sent_direct_to_procurement = (
        sent_direct_to_procurement
    )

    db.session.commit()

    return purchase_request


def list_purchase_requests_for_manager_review() -> list[PurchaseRequest]:
    return (
        PurchaseRequest.query
        .filter(PurchaseRequest.status == "ENVIADA")
        .order_by(PurchaseRequest.created_at.desc(), PurchaseRequest.id.desc())
        .all()
    )


def update_purchase_request_line_by_manager(
    *,
    line_id: int,
    quantity_requested: Decimal,
    cancel_line: bool = False,
) -> PurchaseRequestLine:
    line = PurchaseRequestLine.query.get(line_id)

    if not line:
        raise PurchaseRequestServiceError("La línea indicada no existe.")

    if line.purchase_request.status != "ENVIADA":
        raise PurchaseRequestServiceError("Solo se pueden revisar solicitudes enviadas.")

    if cancel_line:
        line.line_status = "CANCELADA"
    else:
        normalized_quantity = _normalize_decimal(quantity_requested)

        if normalized_quantity <= 0:
            raise PurchaseRequestServiceError("La cantidad debe ser mayor que cero.")

        line.quantity_requested = normalized_quantity

    db.session.commit()
    return line


def approve_purchase_request_for_quotation(
    *,
    request_id: int,
    review_lines: list[dict] | None = None,
) -> PurchaseRequest:
    purchase_request = PurchaseRequest.query.get(request_id)

    if not purchase_request:
        raise PurchaseRequestServiceError("La solicitud indicada no existe.")

    if purchase_request.status != "ENVIADA":
        raise PurchaseRequestServiceError("Solo se pueden aprobar solicitudes enviadas.")

    request_lines_by_id = {
        line.id: line
        for line in purchase_request.lines
    }

    if review_lines is not None:
        for item in review_lines:
            line_id = item.get("line_id")
            cancel_line = bool(item.get("cancel_line"))
            quantity_raw = item.get("quantity_requested")

            line = request_lines_by_id.get(line_id)

            if not line:
                raise PurchaseRequestServiceError(
                    "Una de las líneas enviadas no pertenece a esta solicitud."
                )

            if line.line_status in {"CONVERTIDA_A_OC", "RECIBIDA"}:
                raise PurchaseRequestServiceError(
                    "Una de las líneas ya fue convertida o recibida y no puede modificarse."
                )

            if cancel_line:
                line.line_status = "CANCELADA"
                continue

            quantity = _normalize_decimal(quantity_raw)

            if quantity <= 0:
                raise PurchaseRequestServiceError(
                    "La cantidad de una línea debe ser mayor que cero."
                )

            line.quantity_requested = quantity

            if line.line_status != "CANCELADA":
                line.line_status = "ACTIVA"

    active_lines = [
        line for line in purchase_request.lines
        if line.line_status != "CANCELADA"
    ]

    if not active_lines:
        purchase_request.status = "CANCELADA"
        db.session.commit()
        raise PurchaseRequestServiceError(
            "Todas las líneas fueron canceladas. La solicitud quedó cancelada."
        )

    purchase_request.status = "EN_REVISION_PROVEEDURIA"

    now = datetime.now(UTC)

    for line in active_lines:
        line.line_status = "ENVIADA_A_COTIZAR"
        line.sent_to_quote_at = now

    db.session.commit()
    return purchase_request