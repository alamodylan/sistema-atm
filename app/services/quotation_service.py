from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func

from app.extensions import db
from app.models.quotation_batch import QuotationBatch
from app.models.quotation_line import QuotationLine


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


def _generate_quotation_number() -> str:
    max_id = db.session.query(func.max(QuotationBatch.id)).scalar() or 0
    next_id = int(max_id) + 1
    return f"COT-{next_id:06d}"


def _normalize_decimal(value: Any, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise QuotationServiceError(f"Valor inválido para {field_name}.") from exc


def _validate_quotation_line(line: QuotationLinePayload) -> None:
    if bool(line.article_id) == bool(line.pending_article_id):
        raise QuotationServiceError(
            "Cada línea de cotización debe tener un artículo normal o un artículo pendiente, pero no ambos."
        )

    if _normalize_decimal(line.unit_price, "precio unitario") < 0:
        raise QuotationServiceError("El precio unitario no puede ser negativo.")


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
            brand_model=(line.brand_model or "").strip() or None,
            notes=(line.notes or "").strip() or None,
        )
        db.session.add(quotation_line)

    db.session.commit()
    return quotation_batch


def list_quotation_batches(search: str | None = None) -> list[QuotationBatch]:
    query = QuotationBatch.query

    if search:
        like_value = f"%{search.strip()}%"
        query = query.filter(QuotationBatch.number.ilike(like_value))

    return query.order_by(QuotationBatch.created_at.desc(), QuotationBatch.id.desc()).all()


def get_quotation_batch_or_404(batch_id: int) -> QuotationBatch:
    return QuotationBatch.query.get_or_404(batch_id)