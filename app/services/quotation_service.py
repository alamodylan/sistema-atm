from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func

from app.extensions import db
from app.models.article_supplier import ArticleSupplier
from app.models.purchase_request import PurchaseRequest
from app.models.purchase_request_line import PurchaseRequestLine
from app.models.quotation_batch import QuotationBatch
from app.models.quotation_line import QuotationLine
from app.models.supplier import Supplier


class QuotationServiceError(Exception):
    pass


@dataclass
class QuotationLinePayload:
    purchase_request_line_id: int | None
    supplier_id: int
    quote_date: Any
    unit_price: Decimal
    currency_code: str = "CRC"
    article_id: int | None = None
    pending_article_id: int | None = None
    discount_pct: Decimal = Decimal("0")
    tax_pct: Decimal = Decimal("0")
    tax_included: bool = False
    lead_time_days: int | None = None
    brand_model: str | None = None
    notes: str | None = None
    status: str = "COTIZADA"
    payment_type: str | None = None
    payment_term_months: int | None = None
    origin_type: str | None = None


def _generate_quotation_number() -> str:
    max_id = db.session.query(func.max(QuotationBatch.id)).scalar() or 0
    next_id = int(max_id) + 1
    return f"COT-{next_id:06d}"


def _normalize_decimal(value: Any, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise QuotationServiceError(f"Valor inválido para {field_name}.") from exc


def _normalize_optional_text(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _normalize_optional_int(value: Any, field_name: str) -> int | None:
    if value is None or value == "":
        return None

    try:
        return int(value)
    except Exception as exc:
        raise QuotationServiceError(f"Valor inválido para {field_name}.") from exc


def _validate_quotation_line(line: QuotationLinePayload) -> None:
    if bool(line.article_id) == bool(line.pending_article_id):
        raise QuotationServiceError(
            "Cada línea de cotización debe tener un artículo normal o un artículo pendiente, pero no ambos."
        )

    if not line.supplier_id:
        raise QuotationServiceError("Cada línea de cotización debe tener un proveedor.")

    if _normalize_decimal(line.unit_price, "precio unitario") < 0:
        raise QuotationServiceError("El precio unitario no puede ser negativo.")

    valid_statuses = {
        "BORRADOR",
        "COTIZADA",
        "DESCARTADA",
        "SELECCIONADA",
        "CONVERTIDA_A_OC",
    }

    if line.status not in valid_statuses:
        raise QuotationServiceError("Estado de cotización inválido.")

    valid_payment_types = {None, "CONTADO", "CREDITO"}

    if line.payment_type not in valid_payment_types:
        raise QuotationServiceError("Tipo de pago inválido.")

    valid_origin_types = {None, "LOCAL", "IMPORTACION"}

    if line.origin_type not in valid_origin_types:
        raise QuotationServiceError("Tipo de origen inválido.")

    if line.payment_term_months is not None and line.payment_term_months < 0:
        raise QuotationServiceError("El plazo de pago no puede ser negativo.")


def _ensure_article_supplier(
    *,
    article_id: int | None,
    supplier_id: int,
) -> None:
    if not article_id:
        return

    existing = (
        ArticleSupplier.query
        .filter(
            ArticleSupplier.article_id == article_id,
            ArticleSupplier.supplier_id == supplier_id,
        )
        .first()
    )

    if existing:
        if not existing.is_active:
            existing.is_active = True
        existing.updated_at = datetime.now(UTC)
        return

    article_supplier = ArticleSupplier(
        article_id=article_id,
        supplier_id=supplier_id,
        is_active=True,
    )

    db.session.add(article_supplier)


def _mark_purchase_request_line_as_quoted(
    *,
    purchase_request_line_id: int | None,
    quoted_status: str,
) -> None:
    if not purchase_request_line_id:
        return

    request_line = PurchaseRequestLine.query.get(purchase_request_line_id)

    if not request_line:
        raise QuotationServiceError("La línea de solicitud indicada no existe.")

    if request_line.line_status in {"CONVERTIDA_A_OC", "RECIBIDA", "CANCELADA"}:
        return

    now = datetime.now(UTC)

    if not request_line.sent_to_quote_at:
        request_line.sent_to_quote_at = now

    if quoted_status == "BORRADOR":
        if request_line.line_status in {"ACTIVA", "ENVIADA_A_COTIZAR"}:
            request_line.line_status = "COTIZANDO"
        return

    request_line.line_status = "COTIZADA"
    request_line.quoted_at = now


def _update_purchase_request_status(
    *,
    purchase_request_id: int | None,
) -> None:
    if not purchase_request_id:
        return

    purchase_request = PurchaseRequest.query.get(purchase_request_id)

    if not purchase_request:
        raise QuotationServiceError("La solicitud de compra no existe.")

    if purchase_request.status in {"CONVERTIDA_A_OC", "CERRADA", "CANCELADA"}:
        return

    active_lines = [
        line
        for line in purchase_request.lines
        if line.line_status != "CANCELADA"
    ]

    if not active_lines:
        purchase_request.status = "EN_REVISION_PROVEEDURIA"
        return

    line_statuses = {line.line_status for line in active_lines}

    if line_statuses.issubset({"COTIZADA", "CONVERTIDA_A_OC", "RECIBIDA"}):
        purchase_request.status = "COTIZADA"
        return

    if any(
        status in {"COTIZANDO", "COTIZADA", "CONVERTIDA_A_OC", "RECIBIDA"}
        for status in line_statuses
    ):
        purchase_request.status = "PARCIALMENTE_COTIZADA"
        return

    purchase_request.status = "EN_REVISION_PROVEEDURIA"


def _get_purchase_request_line_or_error(
    purchase_request_line_id: int,
) -> PurchaseRequestLine:
    request_line = PurchaseRequestLine.query.get(purchase_request_line_id)

    if not request_line:
        raise QuotationServiceError("La línea de solicitud indicada no existe.")

    if request_line.line_status in {"CONVERTIDA_A_OC", "RECIBIDA", "CANCELADA"}:
        raise QuotationServiceError(
            "Esta línea de solicitud ya no puede cotizarse porque está convertida, recibida o cancelada."
        )

    return request_line


def _get_purchase_request_id_from_line(request_line: PurchaseRequestLine) -> int | None:
    return getattr(request_line, "purchase_request_id", None)


def _get_article_id_from_line(request_line: PurchaseRequestLine) -> int | None:
    return getattr(request_line, "article_id", None)


def _get_pending_article_id_from_line(request_line: PurchaseRequestLine) -> int | None:
    return getattr(request_line, "pending_article_id", None)


def get_last_price_for_supplier(
    *,
    supplier_id: int,
    article_id: int | None = None,
    pending_article_id: int | None = None,
) -> QuotationLine | None:
    if bool(article_id) == bool(pending_article_id):
        raise QuotationServiceError(
            "Debe indicar un artículo normal o un artículo pendiente para buscar el último precio."
        )

    if not supplier_id:
        raise QuotationServiceError("Debe indicar un proveedor.")

    query = QuotationLine.query.filter(
        QuotationLine.supplier_id == supplier_id,
        QuotationLine.status != "DESCARTADA",
    )

    if article_id:
        query = query.filter(QuotationLine.article_id == article_id)
    else:
        query = query.filter(QuotationLine.pending_article_id == pending_article_id)

    return (
        query
        .order_by(
            QuotationLine.quote_date.desc(),
            QuotationLine.created_at.desc(),
            QuotationLine.id.desc(),
        )
        .first()
    )


def create_single_line_quotation(
    *,
    purchase_request_line_id: int,
    supplier_id: int | None = None,
    new_supplier_name: str | None = None,
    created_by_user_id: int,
    quote_date: Any | None = None,
    unit_price: Any | None = None,
    use_last_price: bool = False,
    currency_code: str = "CRC",
    discount_pct: Any = Decimal("0"),
    tax_pct: Any = Decimal("0"),
    tax_included: bool = False,
    lead_time_days: Any | None = None,
    brand_model: str | None = None,
    notes: str | None = None,
    status: str = "COTIZADA",
    payment_type: str | None = None,
    payment_term_months: Any | None = None,
    origin_type: str | None = None,
) -> QuotationBatch:
    request_line = _get_purchase_request_line_or_error(purchase_request_line_id)

    purchase_request_id = _get_purchase_request_id_from_line(request_line)
    article_id = _get_article_id_from_line(request_line)
    pending_article_id = _get_pending_article_id_from_line(request_line)

    if bool(article_id) == bool(pending_article_id):
        raise QuotationServiceError(
            "La línea de solicitud debe estar relacionada a un artículo normal o pendiente, pero no ambos."
        )

    supplier = Supplier.query.get(supplier_id)

    if new_supplier_name:
        supplier = create_minimal_supplier_for_quotation(
            commercial_name=new_supplier_name,
        )
        supplier_id = supplier.id
    else:
        if not supplier_id:
            raise QuotationServiceError("Debe seleccionar un proveedor.")

        supplier = Supplier.query.get(supplier_id)

        if not supplier:
            raise QuotationServiceError("El proveedor indicado no existe.")

        if hasattr(supplier, "is_active") and not supplier.is_active:
            raise QuotationServiceError("El proveedor indicado está inactivo.")

    quote_date = quote_date or datetime.now(UTC)

    last_line = get_last_price_for_supplier(
        supplier_id=supplier_id,
        article_id=article_id,
        pending_article_id=pending_article_id,
    )

    if use_last_price:
        if not last_line:
            raise QuotationServiceError(
                "No existe un último precio para mantener con este proveedor."
            )

        unit_price = last_line.unit_price

        if discount_pct in (None, ""):
            discount_pct = last_line.discount_pct

        if tax_pct in (None, ""):
            tax_pct = last_line.tax_pct

        if not currency_code:
            currency_code = last_line.currency_code or "CRC"

        if payment_type is None:
            payment_type = last_line.payment_type

        if payment_term_months in (None, ""):
            payment_term_months = last_line.payment_term_months

        if origin_type is None:
            origin_type = last_line.origin_type

        if lead_time_days in (None, ""):
            lead_time_days = last_line.lead_time_days

        if not brand_model:
            brand_model = last_line.brand_model

    if unit_price is None or unit_price == "":
        raise QuotationServiceError("Debe indicar el precio unitario.")

    payload = QuotationLinePayload(
        purchase_request_line_id=purchase_request_line_id,
        supplier_id=supplier_id,
        quote_date=quote_date,
        unit_price=_normalize_decimal(unit_price, "precio unitario"),
        currency_code=(currency_code or "CRC").strip() or "CRC",
        article_id=article_id,
        pending_article_id=pending_article_id,
        discount_pct=_normalize_decimal(discount_pct, "descuento"),
        tax_pct=_normalize_decimal(tax_pct, "impuesto"),
        tax_included=bool(tax_included),
        lead_time_days=_normalize_optional_int(lead_time_days, "plazo de entrega"),
        brand_model=_normalize_optional_text(brand_model),
        notes=_normalize_optional_text(notes),
        status=status,
        payment_type=payment_type,
        payment_term_months=_normalize_optional_int(
            payment_term_months,
            "plazo de pago",
        ),
        origin_type=origin_type,
    )

    _validate_quotation_line(payload)

    quotation_batch = QuotationBatch(
        number=_generate_quotation_number(),
        purchase_request_id=purchase_request_id,
        created_by_user_id=created_by_user_id,
        quote_date=quote_date,
        notes=_normalize_optional_text(notes),
    )

    db.session.add(quotation_batch)
    db.session.flush()

    quotation_line = QuotationLine(
        quotation_batch_id=quotation_batch.id,
        purchase_request_line_id=payload.purchase_request_line_id,
        article_id=payload.article_id,
        pending_article_id=payload.pending_article_id,
        supplier_id=payload.supplier_id,
        quote_date=payload.quote_date,
        currency_code=payload.currency_code,
        unit_price=payload.unit_price,
        discount_pct=payload.discount_pct,
        tax_pct=payload.tax_pct,
        tax_included=payload.tax_included,
        lead_time_days=payload.lead_time_days,
        brand_model=payload.brand_model,
        status=payload.status,
        payment_type=payload.payment_type,
        payment_term_months=payload.payment_term_months,
        origin_type=payload.origin_type,
        notes=payload.notes,
    )

    db.session.add(quotation_line)

    _ensure_article_supplier(
        article_id=payload.article_id,
        supplier_id=payload.supplier_id,
    )

    _mark_purchase_request_line_as_quoted(
        purchase_request_line_id=payload.purchase_request_line_id,
        quoted_status=payload.status,
    )

    db.session.flush()

    _update_purchase_request_status(
        purchase_request_id=purchase_request_id,
    )

    db.session.commit()
    return quotation_batch


def create_quotation_batch(
    *,
    purchase_request_id: int | None,
    created_by_user_id: int,
    quote_date,
    notes: str | None,
    lines: list[QuotationLinePayload],
) -> QuotationBatch:
    if not lines:
        raise QuotationServiceError("La cotización debe incluir al menos una línea.")

    for line in lines:
        _validate_quotation_line(line)

    quotation_batch = QuotationBatch(
        number=_generate_quotation_number(),
        purchase_request_id=purchase_request_id,
        created_by_user_id=created_by_user_id,
        quote_date=quote_date,
        notes=(notes or "").strip() or None,
    )

    db.session.add(quotation_batch)
    db.session.flush()

    for line in lines:
        quotation_line = QuotationLine(
            quotation_batch_id=quotation_batch.id,
            purchase_request_line_id=line.purchase_request_line_id,
            article_id=line.article_id,
            pending_article_id=line.pending_article_id,
            supplier_id=line.supplier_id,
            quote_date=line.quote_date,
            currency_code=(line.currency_code or "CRC").strip() or "CRC",
            unit_price=_normalize_decimal(line.unit_price, "precio unitario"),
            discount_pct=_normalize_decimal(line.discount_pct, "descuento"),
            tax_pct=_normalize_decimal(line.tax_pct, "impuesto"),
            tax_included=bool(line.tax_included),
            lead_time_days=line.lead_time_days,
            brand_model=_normalize_optional_text(line.brand_model),
            status=line.status,
            payment_type=line.payment_type,
            payment_term_months=line.payment_term_months,
            origin_type=line.origin_type,
            notes=_normalize_optional_text(line.notes),
        )

        db.session.add(quotation_line)

        _ensure_article_supplier(
            article_id=line.article_id,
            supplier_id=line.supplier_id,
        )

        _mark_purchase_request_line_as_quoted(
            purchase_request_line_id=line.purchase_request_line_id,
            quoted_status=line.status,
        )

    db.session.flush()

    _update_purchase_request_status(
        purchase_request_id=purchase_request_id,
    )

    db.session.commit()
    return quotation_batch


def get_article_supplier_comparison(
    *,
    article_id: int | None = None,
    pending_article_id: int | None = None,
) -> list[dict]:
    if bool(article_id) == bool(pending_article_id):
        raise QuotationServiceError(
            "Debe indicar un artículo normal o un artículo pendiente para el comparativo."
        )

    query = (
        db.session.query(
            QuotationLine.supplier_id,
            Supplier.commercial_name,
            Supplier.legal_name,
            func.max(QuotationLine.quote_date).label("last_quote_date"),
            func.max(QuotationLine.created_at).label("last_created_at"),
        )
        .join(Supplier, Supplier.id == QuotationLine.supplier_id)
    )

    if article_id:
        query = query.filter(QuotationLine.article_id == article_id)
    else:
        query = query.filter(QuotationLine.pending_article_id == pending_article_id)

    rows = (
        query
        .filter(QuotationLine.status != "DESCARTADA")
        .group_by(
            QuotationLine.supplier_id,
            Supplier.commercial_name,
            Supplier.legal_name,
        )
        .all()
    )

    comparison = []

    for row in rows:
        last_line = get_last_price_for_supplier(
            supplier_id=row.supplier_id,
            article_id=article_id,
            pending_article_id=pending_article_id,
        )

        if not last_line:
            continue

        comparison.append(
            {
                "supplier_id": row.supplier_id,
                "supplier_name": row.commercial_name or row.legal_name or "Proveedor",
                "last_price": last_line.unit_price,
                "last_price_with_tax": last_line.unit_price_with_tax,
                "last_quote_date": last_line.quote_date,
                "currency_code": last_line.currency_code,
                "payment_type": last_line.payment_type,
                "payment_term_months": last_line.payment_term_months,
                "origin_type": last_line.origin_type,
                "brand_model": last_line.brand_model,
                "lead_time_days": last_line.lead_time_days,
                "notes": last_line.notes,
                "quotation_line_id": last_line.id,
                "rank": None,
                "is_best_price": False,
            }
        )

    comparison = sorted(
        comparison,
        key=lambda item: item["last_price_with_tax"] or item["last_price"] or 0,
    )

    for index, item in enumerate(comparison, start=1):
        item["rank"] = index
        item["is_best_price"] = index == 1

    return comparison


def get_comparison_for_purchase_request_line(
    *,
    purchase_request_line_id: int,
) -> list[dict]:
    request_line = _get_purchase_request_line_or_error(purchase_request_line_id)

    article_id = _get_article_id_from_line(request_line)
    pending_article_id = _get_pending_article_id_from_line(request_line)

    return get_article_supplier_comparison(
        article_id=article_id,
        pending_article_id=pending_article_id,
    )


def get_registered_suppliers_for_article(article_id: int) -> list[Supplier]:
    supplier_ids = [
        row.supplier_id
        for row in (
            ArticleSupplier.query
            .filter(
                ArticleSupplier.article_id == article_id,
                ArticleSupplier.is_active.is_(True),
            )
            .all()
        )
    ]

    if not supplier_ids:
        return []

    return (
        Supplier.query
        .filter(
            Supplier.id.in_(supplier_ids),
            Supplier.is_active.is_(True),
        )
        .order_by(Supplier.commercial_name.asc(), Supplier.legal_name.asc())
        .all()
    )


def get_available_suppliers_for_article(
    *,
    article_id: int,
    exclude_supplier_ids: list[int] | None = None,
) -> list[Supplier]:
    exclude_supplier_ids = exclude_supplier_ids or []

    query = Supplier.query.filter(
        Supplier.is_active.is_(True),
    )

    if exclude_supplier_ids:
        query = query.filter(Supplier.id.notin_(exclude_supplier_ids))

    registered_supplier_ids = [
        row.supplier_id
        for row in (
            ArticleSupplier.query
            .filter(
                ArticleSupplier.article_id == article_id,
                ArticleSupplier.is_active.is_(True),
            )
            .all()
        )
    ]

    if registered_supplier_ids:
        query = query.filter(Supplier.id.in_(registered_supplier_ids))
    else:
        return []

    return (
        query
        .order_by(Supplier.commercial_name.asc(), Supplier.legal_name.asc())
        .all()
    )


def get_all_active_suppliers(
    *,
    exclude_supplier_ids: list[int] | None = None,
) -> list[Supplier]:
    exclude_supplier_ids = exclude_supplier_ids or []

    query = Supplier.query.filter(
        Supplier.is_active.is_(True),
    )

    if exclude_supplier_ids:
        query = query.filter(Supplier.id.notin_(exclude_supplier_ids))

    return (
        query
        .order_by(Supplier.commercial_name.asc(), Supplier.legal_name.asc())
        .all()
    )


def list_quotation_batches(search: str | None = None) -> list[QuotationBatch]:
    query = QuotationBatch.query

    if search:
        like_value = f"%{search.strip()}%"
        query = query.filter(QuotationBatch.number.ilike(like_value))

    return (
        query
        .order_by(
            QuotationBatch.created_at.desc(),
            QuotationBatch.id.desc(),
        )
        .all()
    )

def list_quotation_line_groups(search: str | None = None) -> list[dict]:
    search = (search or "").strip()

    query = (
        db.session.query(
            PurchaseRequestLine.id.label("purchase_request_line_id"),
            PurchaseRequestLine.line_status.label("line_status"),
            PurchaseRequestLine.quantity_requested.label("quantity_requested"),
            PurchaseRequest.number.label("purchase_request_number"),
            PurchaseRequest.id.label("purchase_request_id"),
            func.count(QuotationLine.id).label("total_quotes"),
            func.sum(
                db.case(
                    (QuotationLine.status == "BORRADOR", 1),
                    else_=0,
                )
            ).label("draft_quotes"),
            func.sum(
                db.case(
                    (QuotationLine.status == "COTIZADA", 1),
                    else_=0,
                )
            ).label("confirmed_quotes"),
            func.max(QuotationLine.quote_date).label("last_quote_date"),
        )
        .join(
            QuotationLine,
            QuotationLine.purchase_request_line_id == PurchaseRequestLine.id,
        )
        .join(
            PurchaseRequest,
            PurchaseRequest.id == PurchaseRequestLine.purchase_request_id,
        )
        .group_by(
            PurchaseRequestLine.id,
            PurchaseRequestLine.line_status,
            PurchaseRequestLine.quantity_requested,
            PurchaseRequest.number,
            PurchaseRequest.id,
        )
    )

    if search:
        like_value = f"%{search}%"
        query = query.filter(
            db.or_(
                PurchaseRequest.number.ilike(like_value),
                QuotationLine.currency_code.ilike(like_value),
            )
        )

    rows = (
        query
        .order_by(
            func.max(QuotationLine.quote_date).desc(),
            PurchaseRequest.id.desc(),
            PurchaseRequestLine.id.desc(),
        )
        .all()
    )

    groups: list[dict] = []

    for row in rows:
        request_line = PurchaseRequestLine.query.get(row.purchase_request_line_id)

        if not request_line:
            continue

        comparison = get_article_supplier_comparison(
            article_id=getattr(request_line, "article_id", None),
            pending_article_id=getattr(request_line, "pending_article_id", None),
        )

        best = comparison[0] if comparison else None

        groups.append(
            {
                "purchase_request_id": row.purchase_request_id,
                "purchase_request_number": row.purchase_request_number,
                "purchase_request_line_id": row.purchase_request_line_id,
                "item_code": request_line.item_code or "-",
                "item_name": request_line.item_name or "Sin artículo",
                "quantity_requested": row.quantity_requested,
                "line_status": row.line_status,
                "total_quotes": int(row.total_quotes or 0),
                "draft_quotes": int(row.draft_quotes or 0),
                "confirmed_quotes": int(row.confirmed_quotes or 0),
                "best_price": best.get("last_price_with_tax") or best.get("last_price") if best else None,
                "best_supplier": best.get("supplier_name") if best else None,
                "last_quote_date": row.last_quote_date,
            }
        )

    return groups

def get_quotation_batch_or_404(batch_id: int) -> QuotationBatch:
    return QuotationBatch.query.get_or_404(batch_id)

def create_minimal_supplier_for_quotation(
    *,
    commercial_name: str,
) -> Supplier:
    commercial_name = (commercial_name or "").strip()

    if not commercial_name:
        raise QuotationServiceError("Debe indicar el nombre del nuevo proveedor.")

    existing = (
        Supplier.query
        .filter(func.lower(Supplier.commercial_name) == commercial_name.lower())
        .first()
    )

    if existing:
        if not existing.is_active:
            existing.is_active = True
        return existing

    supplier = Supplier(
        commercial_name=commercial_name,
        is_active=True,
    )

    db.session.add(supplier)
    db.session.flush()

    return supplier