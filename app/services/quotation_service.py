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
from app.models.article import Article
from app.models.pending_article import PendingArticle
from app.models.purchase_order_candidate import PurchaseOrderCandidate
from app.models.article_quotation_category import ArticleQuotationCategory
from app.models.quotation_category import QuotationCategory


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
    next_id = (
        db.session.query(
            func.nextval("atm.quotation_batches_id_seq")
        ).scalar()
    )

    return f"COT-{int(next_id):06d}"


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

def _calculate_quotation_amounts(
    quotation_line: QuotationLine,
    quantity: Any = Decimal("1"),
) -> dict:
    """
    Calcula los importes reales de una línea de cotización.

    Respeta:
    - precio con IVA incluido;
    - precio sin IVA;
    - porcentaje de descuento;
    - porcentaje de impuesto;
    - cantidad solicitada.

    El cálculo se utiliza tanto en el comparativo como en la pre-OC.
    """

    quantity_decimal = _normalize_decimal(
        quantity or Decimal("0"),
        "cantidad",
    )

    unit_price = _normalize_decimal(
        quotation_line.unit_price or Decimal("0"),
        "precio unitario",
    )

    discount_pct = _normalize_decimal(
        quotation_line.discount_pct or Decimal("0"),
        "descuento",
    )

    tax_pct = _normalize_decimal(
        quotation_line.tax_pct or Decimal("0"),
        "impuesto",
    )

    if quantity_decimal < 0:
        raise QuotationServiceError(
            "La cantidad no puede ser negativa."
        )

    if unit_price < 0:
        raise QuotationServiceError(
            "El precio unitario no puede ser negativo."
        )

    if discount_pct < 0 or discount_pct > 100:
        raise QuotationServiceError(
            "El porcentaje de descuento debe estar entre 0 y 100."
        )

    if tax_pct < 0:
        raise QuotationServiceError(
            "El porcentaje de impuesto no puede ser negativo."
        )

    tax_factor = (
        Decimal("1")
        + (tax_pct / Decimal("100"))
    )

    if quotation_line.tax_included:
        unit_subtotal = (
            unit_price / tax_factor
            if tax_pct > 0
            else unit_price
        )
    else:
        unit_subtotal = unit_price

    unit_discount_amount = (
        unit_subtotal
        * (discount_pct / Decimal("100"))
    )

    unit_taxable_base = (
        unit_subtotal - unit_discount_amount
    )

    unit_tax_amount = (
        unit_taxable_base
        * (tax_pct / Decimal("100"))
    )

    unit_total = (
        unit_taxable_base + unit_tax_amount
    )

    line_subtotal = (
        quantity_decimal * unit_subtotal
    )

    line_discount_amount = (
        quantity_decimal * unit_discount_amount
    )

    line_taxable_base = (
        quantity_decimal * unit_taxable_base
    )

    line_tax_amount = (
        quantity_decimal * unit_tax_amount
    )

    line_total = (
        quantity_decimal * unit_total
    )

    return {
        "quantity": quantity_decimal,
        "unit_price": unit_price,
        "unit_subtotal": unit_subtotal,
        "discount_pct": discount_pct,
        "unit_discount_amount": unit_discount_amount,
        "unit_taxable_base": unit_taxable_base,
        "tax_pct": tax_pct,
        "unit_tax_amount": unit_tax_amount,
        "unit_total": unit_total,
        "line_subtotal": line_subtotal,
        "line_discount_amount": line_discount_amount,
        "line_taxable_base": line_taxable_base,
        "line_tax_amount": line_tax_amount,
        "line_total": line_total,
    }

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

def list_quotation_request_groups(
    search: str | None = None,
) -> list[dict]:
    search = (search or "").strip()

    result: list[dict] = []

    allowed_request_statuses = {
        "EN_REVISION_PROVEEDURIA",
        "PARCIALMENTE_COTIZADA",
        "COTIZADA",
    }

    # =====================================================
    # COTIZACIONES DESDE SOLICITUD
    # =====================================================
    query = (
        db.session.query(
            PurchaseRequest.id.label("purchase_request_id"),
            PurchaseRequest.number.label("purchase_request_number"),

            func.count(
                func.distinct(PurchaseRequestLine.id)
            ).label("total_lines"),

            func.count(
                func.distinct(
                    db.case(
                        (
                            PurchaseRequestLine.line_status == "COTIZADA",
                            PurchaseRequestLine.id,
                        ),
                        else_=None,
                    )
                )
            ).label("quoted_lines"),

            func.count(
                func.distinct(
                    db.case(
                        (
                            PurchaseRequestLine.line_status != "COTIZADA",
                            PurchaseRequestLine.id,
                        ),
                        else_=None,
                    )
                )
            ).label("pending_lines"),

            func.max(
                QuotationLine.quote_date
            ).label("last_quote_date"),
        )
        .join(
            PurchaseRequestLine,
            PurchaseRequestLine.purchase_request_id
            == PurchaseRequest.id,
        )
        .outerjoin(
            QuotationLine,
            QuotationLine.purchase_request_line_id
            == PurchaseRequestLine.id,
        )
        .filter(
            PurchaseRequest.status.in_(
                allowed_request_statuses
            ),
            PurchaseRequestLine.line_status != "CANCELADA",
        )
        .group_by(
            PurchaseRequest.id,
            PurchaseRequest.number,
        )
    )

    if search:
        like_value = f"%{search}%"

        query = query.filter(
            PurchaseRequest.number.ilike(like_value)
        )

    rows = query.all()

    for row in rows:
        result.append(
            {
                "group_type": "REQUEST",
                "purchase_request_id": row.purchase_request_id,
                "purchase_request_number": (
                    row.purchase_request_number
                ),
                "item_name": None,
                "item_code": None,
                "article_id": None,
                "pending_article_id": None,
                "total_lines": int(row.total_lines or 0),
                "quoted_lines": int(row.quoted_lines or 0),
                "pending_lines": int(row.pending_lines or 0),
                "total_quotes": None,
                "last_quote_date": row.last_quote_date,
            }
        )

    # =====================================================
    # COTIZACIONES LIBRES - ARTÍCULO EXISTENTE
    # =====================================================
    free_article_rows = (
        db.session.query(
            QuotationLine.article_id,
            Article.code.label("item_code"),
            Article.name.label("item_name"),
            func.count(
                QuotationLine.id
            ).label("total_quotes"),
            func.max(
                QuotationLine.quote_date
            ).label("last_quote_date"),
        )
        .join(
            Article,
            Article.id == QuotationLine.article_id,
        )
        .filter(
            QuotationLine.purchase_request_line_id.is_(None),
            QuotationLine.article_id.isnot(None),
        )
        .group_by(
            QuotationLine.article_id,
            Article.code,
            Article.name,
        )
    )

    if search:
        like_value = f"%{search}%"

        free_article_rows = free_article_rows.filter(
            db.or_(
                Article.code.ilike(like_value),
                Article.name.ilike(like_value),
            )
        )

    for row in free_article_rows.all():
        result.append(
            {
                "group_type": "FREE_ARTICLE",
                "purchase_request_id": None,
                "purchase_request_number": "Cotización libre",
                "item_name": row.item_name,
                "item_code": row.item_code,
                "article_id": row.article_id,
                "pending_article_id": None,
                "total_lines": 1,
                "quoted_lines": int(row.total_quotes or 0),
                "pending_lines": 0,
                "total_quotes": int(row.total_quotes or 0),
                "last_quote_date": row.last_quote_date,
            }
        )

    # =====================================================
    # COTIZACIONES LIBRES - ARTÍCULO PENDIENTE
    # =====================================================
    free_pending_rows = (
        db.session.query(
            QuotationLine.pending_article_id,
            PendingArticle.provisional_code.label("item_code"),
            PendingArticle.provisional_name.label("item_name"),
            func.count(
                QuotationLine.id
            ).label("total_quotes"),
            func.max(
                QuotationLine.quote_date
            ).label("last_quote_date"),
        )
        .join(
            PendingArticle,
            PendingArticle.id
            == QuotationLine.pending_article_id,
        )
        .filter(
            QuotationLine.purchase_request_line_id.is_(None),
            QuotationLine.pending_article_id.isnot(None),
        )
        .group_by(
            QuotationLine.pending_article_id,
            PendingArticle.provisional_code,
            PendingArticle.provisional_name,
        )
    )

    if search:
        like_value = f"%{search}%"

        free_pending_rows = free_pending_rows.filter(
            db.or_(
                PendingArticle.provisional_code.ilike(
                    like_value
                ),
                PendingArticle.provisional_name.ilike(
                    like_value
                ),
            )
        )

    for row in free_pending_rows.all():
        result.append(
            {
                "group_type": "FREE_PENDING",
                "purchase_request_id": None,
                "purchase_request_number": "Cotización libre",
                "item_name": row.item_name,
                "item_code": row.item_code,
                "article_id": None,
                "pending_article_id": row.pending_article_id,
                "total_lines": 1,
                "quoted_lines": int(row.total_quotes or 0),
                "pending_lines": 0,
                "total_quotes": int(row.total_quotes or 0),
                "last_quote_date": row.last_quote_date,
            }
        )

    result.sort(
        key=lambda item: (
            item["last_quote_date"] or datetime.min.date()
        ),
        reverse=True,
    )

    return result

def _ensure_article_supplier(
    *,
    article_id: int | None,
    supplier_id: int,
) -> None:

    if not article_id:
        return

    existing = db.session.execute(
        db.text("""
            SELECT id, is_active
            FROM atm.article_suppliers
            WHERE article_id = :article_id
              AND supplier_id = :supplier_id
            LIMIT 1
        """),
        {
            "article_id": article_id,
            "supplier_id": supplier_id,
        }
    ).fetchone()

    if existing:

        if not existing.is_active:
            db.session.execute(
                db.text("""
                    UPDATE atm.article_suppliers
                    SET is_active = TRUE,
                        updated_at = NOW()
                    WHERE id = :id
                """),
                {"id": existing.id}
            )

        return

    db.session.execute(
        db.text("""
            INSERT INTO atm.article_suppliers (
                article_id,
                supplier_id,
                is_active,
                created_at,
                updated_at
            )
            VALUES (
                :article_id,
                :supplier_id,
                TRUE,
                NOW(),
                NOW()
            )
        """),
        {
            "article_id": article_id,
            "supplier_id": supplier_id,
        }
    )


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
    request_line = PurchaseRequestLine.query.get(
        purchase_request_line_id
    )

    if not request_line:
        raise QuotationServiceError(
            "La línea de solicitud indicada no existe."
        )

    if request_line.line_status in {
        "CONVERTIDA_A_OC",
        "RECIBIDA",
        "CANCELADA",
    }:
        raise QuotationServiceError(
            "Esta línea de solicitud ya no puede cotizarse "
            "porque está convertida, recibida o cancelada."
        )

    purchase_request = request_line.purchase_request

    if not purchase_request:
        raise QuotationServiceError(
            "La línea no está vinculada a una solicitud "
            "de compra válida."
        )

    allowed_request_statuses = {
        "EN_REVISION_PROVEEDURIA",
        "PARCIALMENTE_COTIZADA",
        "COTIZADA",
    }

    if purchase_request.status not in allowed_request_statuses:
        if purchase_request.status == "ENVIADA":
            raise QuotationServiceError(
                "Esta solicitud todavía está pendiente de "
                "aprobación por Jefatura y no puede cotizarse."
            )

        if purchase_request.status == "BORRADOR":
            raise QuotationServiceError(
                "Esta solicitud todavía está en borrador "
                "y no puede cotizarse."
            )

        if purchase_request.status == "CANCELADA":
            raise QuotationServiceError(
                "Esta solicitud fue cancelada y no puede cotizarse."
            )

        if purchase_request.status in {
            "CONVERTIDA_A_OC",
            "CERRADA",
        }:
            raise QuotationServiceError(
                "Esta solicitud ya completó su proceso "
                "y no puede recibir nuevas cotizaciones."
            )

        raise QuotationServiceError(
            "El estado actual de la solicitud no permite cotizar."
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
            "Debe indicar un artículo normal o un "
            "artículo pendiente para el comparativo."
        )

    query = (
        db.session.query(
            QuotationLine,
            Supplier.commercial_name,
            Supplier.legal_name,
        )
        .join(
            Supplier,
            Supplier.id == QuotationLine.supplier_id,
        )
        .filter(
            QuotationLine.status != "DESCARTADA",
        )
    )

    if article_id is not None:
        query = query.filter(
            QuotationLine.article_id == article_id
        )
    else:
        query = query.filter(
            QuotationLine.pending_article_id
            == pending_article_id
        )

    rows = (
        query
        .order_by(
            QuotationLine.supplier_id.asc(),
            QuotationLine.quote_date.desc(),
            QuotationLine.created_at.desc(),
            QuotationLine.id.desc(),
        )
        .all()
    )

    comparison: list[dict] = []
    processed_supplier_ids: set[int] = set()

    for quotation_line, commercial_name, legal_name in rows:
        supplier_id = quotation_line.supplier_id

        # Solo toma la cotización más reciente de cada proveedor.
        if supplier_id in processed_supplier_ids:
            continue

        processed_supplier_ids.add(supplier_id)

        unit_price = Decimal(
            str(quotation_line.unit_price or 0)
        )

        tax_pct = Decimal(
            str(quotation_line.tax_pct or 0)
        )

        discount_pct = Decimal(
            str(quotation_line.discount_pct or 0)
        )

        tax_factor = (
            Decimal("1")
            + (tax_pct / Decimal("100"))
        )

        if quotation_line.tax_included:
            subtotal = (
                unit_price / tax_factor
                if tax_pct > 0
                else unit_price
            )
        else:
            subtotal = unit_price

        discount_amount = (
            subtotal
            * (discount_pct / Decimal("100"))
        )

        taxable_base = subtotal - discount_amount

        tax_amount = (
            taxable_base
            * (tax_pct / Decimal("100"))
        )

        total_amount = taxable_base + tax_amount

        comparison.append(
            {
                "supplier_id": supplier_id,
                "supplier_name": (
                    commercial_name
                    or legal_name
                    or "Proveedor"
                ),
                "last_price": unit_price,
                "subtotal": subtotal,
                "discount_pct": discount_pct,
                "discount_amount": discount_amount,
                "tax_pct": tax_pct,
                "tax_amount": tax_amount,
                "tax_included": bool(
                    quotation_line.tax_included
                ),
                "taxable_base": taxable_base,
                "total_amount": total_amount,
                "last_quote_date": (
                    quotation_line.quote_date
                ),
                "currency_code": (
                    quotation_line.currency_code
                ),
                "payment_type": (
                    quotation_line.payment_type
                ),
                "payment_term_months": (
                    quotation_line.payment_term_months
                ),
                "origin_type": (
                    quotation_line.origin_type
                ),
                "brand_model": (
                    quotation_line.brand_model
                ),
                "lead_time_days": (
                    quotation_line.lead_time_days
                ),
                "notes": quotation_line.notes,
                "quotation_line_id": quotation_line.id,
                "rank": None,
                "is_best_price": False,
            }
        )

    comparison.sort(
        key=lambda item: (
            item["total_amount"]
            or item["subtotal"]
            or Decimal("0")
        )
    )

    for index, item in enumerate(
        comparison,
        start=1,
    ):
        item["rank"] = index
        item["is_best_price"] = index == 1

    return comparison


def get_comparison_for_purchase_request_line(
    *,
    purchase_request_line_id: int,
) -> list[dict]:
    """
    Obtiene el comparativo exclusivo de una línea de solicitud.

    Por cada proveedor conserva la cotización más reciente.

    Los precios únicamente se comparan dentro de la misma moneda.
    """

    request_line = _get_purchase_request_line_or_error(
        purchase_request_line_id
    )

    selected_candidate = (
        PurchaseOrderCandidate.query
        .filter(
            PurchaseOrderCandidate.purchase_request_line_id
            == purchase_request_line_id,
            PurchaseOrderCandidate.status.in_(
                {"PENDING", "USED"}
            ),
        )
        .order_by(
            PurchaseOrderCandidate.id.desc()
        )
        .first()
    )

    rows = (
        db.session.query(
            QuotationLine,
            Supplier.commercial_name,
            Supplier.legal_name,
        )
        .join(
            Supplier,
            Supplier.id
            == QuotationLine.supplier_id,
        )
        .filter(
            QuotationLine.purchase_request_line_id
            == purchase_request_line_id,
            QuotationLine.status
            != "DESCARTADA",
        )
        .order_by(
            QuotationLine.supplier_id.asc(),
            QuotationLine.quote_date.desc(),
            QuotationLine.created_at.desc(),
            QuotationLine.id.desc(),
        )
        .all()
    )

    comparison: list[dict] = []
    processed_supplier_ids: set[int] = set()

    quantity_requested = _normalize_decimal(
        request_line.quantity_requested
        or Decimal("0"),
        "cantidad solicitada",
    )

    for (
        quotation_line,
        commercial_name,
        legal_name,
    ) in rows:
        supplier_id = quotation_line.supplier_id

        if supplier_id in processed_supplier_ids:
            continue

        processed_supplier_ids.add(
            supplier_id
        )

        amounts = _calculate_quotation_amounts(
            quotation_line,
            quantity_requested,
        )

        currency_code = (
            quotation_line.currency_code
            or "CRC"
        ).strip().upper()

        is_selected = bool(
            selected_candidate
            and selected_candidate.quotation_line_id
            == quotation_line.id
        )

        comparison.append(
            {
                "supplier_id": supplier_id,
                "supplier_name": (
                    commercial_name
                    or legal_name
                    or "Proveedor"
                ),
                "quotation_line_id": (
                    quotation_line.id
                ),
                "purchase_request_line_id": (
                    purchase_request_line_id
                ),
                "quantity_requested": (
                    quantity_requested
                ),
                "quote_date": (
                    quotation_line.quote_date
                ),
                "last_quote_date": (
                    quotation_line.quote_date
                ),
                "currency_code": currency_code,
                "unit_price": (
                    amounts["unit_price"]
                ),
                "last_price": (
                    amounts["unit_price"]
                ),
                "unit_subtotal": (
                    amounts["unit_subtotal"]
                ),
                "discount_pct": (
                    amounts["discount_pct"]
                ),
                "unit_discount_amount": (
                    amounts[
                        "unit_discount_amount"
                    ]
                ),
                "taxable_base_unit": (
                    amounts[
                        "unit_taxable_base"
                    ]
                ),
                "tax_pct": amounts["tax_pct"],
                "unit_tax_amount": (
                    amounts["unit_tax_amount"]
                ),
                "unit_total": (
                    amounts["unit_total"]
                ),
                "line_subtotal": (
                    amounts["line_subtotal"]
                ),
                "line_discount_amount": (
                    amounts[
                        "line_discount_amount"
                    ]
                ),
                "line_taxable_base": (
                    amounts[
                        "line_taxable_base"
                    ]
                ),
                "line_tax_amount": (
                    amounts["line_tax_amount"]
                ),
                "line_total": (
                    amounts["line_total"]
                ),

                # Compatibilidad con templates actuales.
                "subtotal": (
                    amounts["unit_subtotal"]
                ),
                "discount_amount": (
                    amounts[
                        "unit_discount_amount"
                    ]
                ),
                "tax_amount": (
                    amounts["unit_tax_amount"]
                ),
                "total_amount": (
                    amounts["unit_total"]
                ),

                "tax_included": bool(
                    quotation_line.tax_included
                ),
                "payment_type": (
                    quotation_line.payment_type
                ),
                "payment_term_months": (
                    quotation_line.payment_term_months
                ),
                "origin_type": (
                    quotation_line.origin_type
                ),
                "brand_model": (
                    quotation_line.brand_model
                ),
                "lead_time_days": (
                    quotation_line.lead_time_days
                ),
                "notes": quotation_line.notes,
                "status": quotation_line.status,
                "rank": None,
                "currency_rank": None,
                "is_best_price": False,
                "is_selected": is_selected,
                "selection_status": (
                    selected_candidate.status
                    if is_selected
                    else None
                ),
                "is_selection_locked": bool(
                    is_selected
                    and selected_candidate.status
                    == "USED"
                ),
                "purchase_order_id": (
                    selected_candidate.purchase_order_id
                    if is_selected
                    else None
                ),
            }
        )

    comparison.sort(
        key=lambda item: (
            item["currency_code"],
            item["unit_total"],
            item["supplier_name"].lower(),
        )
    )

    currencies = {
        item["currency_code"]
        for item in comparison
    }

    has_mixed_currencies = (
        len(currencies) > 1
    )

    comparisons_by_currency: dict[
        str,
        list[dict],
    ] = {}

    for item in comparison:
        comparisons_by_currency.setdefault(
            item["currency_code"],
            [],
        ).append(item)

    global_rank = 1

    for currency_code in sorted(
        comparisons_by_currency
    ):
        currency_items = (
            comparisons_by_currency[
                currency_code
            ]
        )

        minimum_total = min(
            item["unit_total"]
            for item in currency_items
        )

        for currency_rank, item in enumerate(
            currency_items,
            start=1,
        ):
            item["rank"] = global_rank
            item["currency_rank"] = (
                currency_rank
            )
            item["is_best_price"] = (
                item["unit_total"]
                == minimum_total
            )
            item["has_mixed_currencies"] = (
                has_mixed_currencies
            )

            global_rank += 1

    return comparison

def get_category_comparison_matrix(
    *,
    purchase_request_id: int,
    quotation_category_id: int | None,
) -> dict:
    """
    Construye el comparativo de cotizaciones de una categoría dentro
    de una solicitud de compra.

    Reglas:
    - La categoría se obtiene desde ArticleQuotationCategory.
    - quotation_category_id recibe el ID real de QuotationCategory.
    - None o 0 representan artículos sin categoría.
    - Solo se incluyen líneas no canceladas.
    - Por cada línea y proveedor se conserva la cotización más reciente.
    - Las selecciones vigentes provienen de PurchaseOrderCandidate.
    - Los candidatos USED quedan bloqueados.
    - No se comparan precios entre monedas distintas.
    """

    purchase_request = PurchaseRequest.query.get(
        purchase_request_id
    )

    if not purchase_request:
        raise QuotationServiceError(
            "La solicitud de compra indicada no existe."
        )

    category_id: int | None = None

    if quotation_category_id not in {
        None,
        "",
        0,
        "0",
    }:
        try:
            category_id = int(
                quotation_category_id
            )
        except (TypeError, ValueError) as exc:
            raise QuotationServiceError(
                "La categoría indicada no es válida."
            ) from exc

    quotation_category = None

    if category_id is not None:
        quotation_category = (
            QuotationCategory.query
            .filter(
                QuotationCategory.id == category_id,
                QuotationCategory.is_active.is_(True),
            )
            .first()
        )

        if not quotation_category:
            raise QuotationServiceError(
                "La categoría indicada no existe o está inactiva."
            )

    category_label = (
        quotation_category.name
        if quotation_category
        else "Sin categoría"
    )

    # =====================================================
    # 1. CARGAR LAS LÍNEAS DE LA SOLICITUD
    # =====================================================

    request_lines = (
        PurchaseRequestLine.query
        .filter(
            PurchaseRequestLine.purchase_request_id
            == purchase_request_id,
            PurchaseRequestLine.line_status
            != "CANCELADA",
        )
        .order_by(
            PurchaseRequestLine.id.asc(),
        )
        .all()
    )

    if not request_lines:
        return {
            "purchase_request_id": purchase_request.id,
            "purchase_request_number": purchase_request.number,
            "purchase_request_status": purchase_request.status,
            "purchase_request": purchase_request,
            "category_id": category_id,
            "category_code": category_id,
            "category_label": category_label,
            "quotation_category": quotation_category,
            "is_uncategorized": category_id is None,
            "suppliers": [],
            "lines": [],
            "total_lines": 0,
            "total_suppliers": 0,
            "total_quotations": 0,
            "selected_lines": 0,
            "pending_selection_lines": 0,
        }

    article_ids = {
        line.article_id
        for line in request_lines
        if line.article_id is not None
    }

    pending_article_ids = {
        line.pending_article_id
        for line in request_lines
        if line.pending_article_id is not None
    }

    # =====================================================
    # 2. CARGAR ASIGNACIONES DE CATEGORÍA
    # =====================================================

    assignment_filters = []

    if article_ids:
        assignment_filters.append(
            ArticleQuotationCategory.article_id.in_(
                article_ids
            )
        )

    if pending_article_ids:
        assignment_filters.append(
            ArticleQuotationCategory.pending_article_id.in_(
                pending_article_ids
            )
        )

    article_category_map: dict[int, int] = {}
    pending_category_map: dict[int, int] = {}

    if assignment_filters:
        assignments = (
            ArticleQuotationCategory.query
            .filter(
                db.or_(*assignment_filters)
            )
            .all()
        )

        for assignment in assignments:
            if assignment.article_id is not None:
                article_category_map[
                    assignment.article_id
                ] = assignment.quotation_category_id

            if assignment.pending_article_id is not None:
                pending_category_map[
                    assignment.pending_article_id
                ] = assignment.quotation_category_id

    # =====================================================
    # 3. FILTRAR LAS LÍNEAS POR CATEGORÍA
    # =====================================================

    filtered_request_lines: list[
        PurchaseRequestLine
    ] = []

    for request_line in request_lines:
        assigned_category_id = None

        if request_line.article_id is not None:
            assigned_category_id = (
                article_category_map.get(
                    request_line.article_id
                )
            )

        elif request_line.pending_article_id is not None:
            assigned_category_id = (
                pending_category_map.get(
                    request_line.pending_article_id
                )
            )

        if category_id is None:
            if assigned_category_id is None:
                filtered_request_lines.append(
                    request_line
                )
        elif assigned_category_id == category_id:
            filtered_request_lines.append(
                request_line
            )

    if not filtered_request_lines:
        return {
            "purchase_request_id": purchase_request.id,
            "purchase_request_number": purchase_request.number,
            "purchase_request_status": purchase_request.status,
            "purchase_request": purchase_request,
            "category_id": category_id,
            "category_code": category_id,
            "category_label": category_label,
            "quotation_category": quotation_category,
            "is_uncategorized": category_id is None,
            "suppliers": [],
            "lines": [],
            "total_lines": 0,
            "total_suppliers": 0,
            "total_quotations": 0,
            "selected_lines": 0,
            "pending_selection_lines": 0,
        }

    request_line_ids = [
        request_line.id
        for request_line in filtered_request_lines
    ]

    # =====================================================
    # 4. CARGAR COTIZACIONES
    # =====================================================

    quotation_rows = (
        db.session.query(
            QuotationLine,
            Supplier.commercial_name,
            Supplier.legal_name,
        )
        .join(
            Supplier,
            Supplier.id == QuotationLine.supplier_id,
        )
        .filter(
            QuotationLine.purchase_request_line_id.in_(
                request_line_ids
            ),
            QuotationLine.status != "DESCARTADA",
        )
        .order_by(
            QuotationLine.purchase_request_line_id.asc(),
            QuotationLine.supplier_id.asc(),
            QuotationLine.quote_date.desc(),
            QuotationLine.created_at.desc(),
            QuotationLine.id.desc(),
        )
        .all()
    )

    # =====================================================
    # 5. CARGAR SELECCIONES DE PRE-OC
    # =====================================================

    candidate_rows = (
        PurchaseOrderCandidate.query
        .filter(
            PurchaseOrderCandidate.purchase_request_line_id.in_(
                request_line_ids
            ),
            PurchaseOrderCandidate.status.in_(
                {"PENDING", "USED"}
            ),
        )
        .order_by(
            PurchaseOrderCandidate.purchase_request_line_id.asc(),
            PurchaseOrderCandidate.id.desc(),
        )
        .all()
    )

    candidate_by_request_line: dict[
        int,
        PurchaseOrderCandidate,
    ] = {}

    for candidate in candidate_rows:
        candidate_by_request_line.setdefault(
            candidate.purchase_request_line_id,
            candidate,
        )

    # =====================================================
    # 6. INDEXAR PROVEEDORES Y COTIZACIONES
    # =====================================================

    supplier_map: dict[int, dict] = {}

    latest_quotation_map: dict[
        tuple[int, int],
        tuple[QuotationLine, str],
    ] = {}

    quotation_by_id: dict[
        int,
        tuple[QuotationLine, str],
    ] = {}

    for (
        quotation_line,
        commercial_name,
        legal_name,
    ) in quotation_rows:
        supplier_name = (
            commercial_name
            or legal_name
            or f"Proveedor {quotation_line.supplier_id}"
        )

        supplier_map.setdefault(
            quotation_line.supplier_id,
            {
                "supplier_id": quotation_line.supplier_id,
                "supplier_name": supplier_name,
            },
        )

        quotation_by_id[
            quotation_line.id
        ] = (
            quotation_line,
            supplier_name,
        )

        quotation_key = (
            quotation_line.purchase_request_line_id,
            quotation_line.supplier_id,
        )

        latest_quotation_map.setdefault(
            quotation_key,
            (
                quotation_line,
                supplier_name,
            ),
        )

    suppliers = sorted(
        supplier_map.values(),
        key=lambda supplier: (
            supplier["supplier_name"].lower(),
            supplier["supplier_id"],
        ),
    )

    # =====================================================
    # 7. CONSTRUIR MATRIZ
    # =====================================================

    matrix_lines: list[dict] = []
    selected_lines = 0
    total_quotations = 0

    for request_line in filtered_request_lines:
        if request_line.article_id is not None:
            item_type = "ARTICLE"
            item_id = request_line.article_id
        elif request_line.pending_article_id is not None:
            item_type = "PENDING"
            item_id = request_line.pending_article_id
        else:
            item_type = None
            item_id = None

        item_code = (
            request_line.item_code or "-"
        )

        item_name = (
            request_line.item_name or "Sin artículo"
        )

        quantity_requested = _normalize_decimal(
            request_line.quantity_requested
            or Decimal("0"),
            "cantidad solicitada",
        )

        selected_candidate = (
            candidate_by_request_line.get(
                request_line.id
            )
        )

        if selected_candidate:
            selected_lines += 1

        selected_quotation_data = None

        if (
            selected_candidate
            and selected_candidate.quotation_line_id
            in quotation_by_id
        ):
            (
                selected_quotation,
                selected_supplier_name,
            ) = quotation_by_id[
                selected_candidate.quotation_line_id
            ]

            selected_amounts = (
                _calculate_quotation_amounts(
                    selected_quotation,
                    quantity_requested,
                )
            )

            selected_quotation_data = {
                "candidate_id": selected_candidate.id,
                "quotation_line_id": (
                    selected_quotation.id
                ),
                "supplier_id": (
                    selected_quotation.supplier_id
                ),
                "supplier_name": (
                    selected_supplier_name
                ),
                "currency_code": (
                    selected_quotation.currency_code
                    or "CRC"
                ),
                "unit_total": (
                    selected_amounts["unit_total"]
                ),
                "line_total": (
                    selected_amounts["line_total"]
                ),
                "status": selected_candidate.status,
                "is_locked": (
                    selected_candidate.status
                    == "USED"
                ),
                "purchase_order_id": (
                    selected_candidate.purchase_order_id
                ),
            }

        cells: list[dict] = []
        calculated_cells: list[dict] = []
        line_currency_codes: set[str] = set()

        for supplier in suppliers:
            supplier_id = supplier[
                "supplier_id"
            ]

            quotation_data = (
                latest_quotation_map.get(
                    (
                        request_line.id,
                        supplier_id,
                    )
                )
            )

            if not quotation_data:
                cells.append(
                    {
                        "supplier_id": supplier_id,
                        "supplier_name": (
                            supplier["supplier_name"]
                        ),
                        "has_quotation": False,
                        "quotation": None,
                    }
                )
                continue

            (
                quotation_line,
                supplier_name,
            ) = quotation_data

            amounts = _calculate_quotation_amounts(
                quotation_line,
                quantity_requested,
            )

            currency_code = (
                quotation_line.currency_code
                or "CRC"
            ).strip().upper()

            line_currency_codes.add(
                currency_code
            )

            total_quotations += 1

            is_selected = bool(
                selected_candidate
                and selected_candidate.quotation_line_id
                == quotation_line.id
            )

            is_selectable = (
                quotation_line.status
                not in {
                    "BORRADOR",
                    "DESCARTADA",
                    "CONVERTIDA_A_OC",
                }
                and amounts["unit_price"] > 0
                and not (
                    selected_candidate
                    and selected_candidate.status
                    == "USED"
                    and not is_selected
                )
            )

            cell = {
                "supplier_id": supplier_id,
                "supplier_name": supplier_name,
                "has_quotation": True,
                "quotation": {
                    "quotation_line_id": (
                        quotation_line.id
                    ),
                    "purchase_request_line_id": (
                        request_line.id
                    ),
                    "quote_date": (
                        quotation_line.quote_date
                    ),
                    "created_at": (
                        quotation_line.created_at
                    ),
                    "currency_code": currency_code,
                    "unit_price": (
                        amounts["unit_price"]
                    ),
                    "unit_subtotal": (
                        amounts["unit_subtotal"]
                    ),
                    "discount_pct": (
                        amounts["discount_pct"]
                    ),
                    "unit_discount_amount": (
                        amounts[
                            "unit_discount_amount"
                        ]
                    ),
                    "unit_taxable_base": (
                        amounts[
                            "unit_taxable_base"
                        ]
                    ),
                    "tax_pct": (
                        amounts["tax_pct"]
                    ),
                    "unit_tax_amount": (
                        amounts["unit_tax_amount"]
                    ),
                    "unit_total": (
                        amounts["unit_total"]
                    ),
                    "line_subtotal": (
                        amounts["line_subtotal"]
                    ),
                    "line_discount_amount": (
                        amounts[
                            "line_discount_amount"
                        ]
                    ),
                    "line_taxable_base": (
                        amounts[
                            "line_taxable_base"
                        ]
                    ),
                    "line_tax_amount": (
                        amounts["line_tax_amount"]
                    ),
                    "line_total": (
                        amounts["line_total"]
                    ),
                    "tax_included": bool(
                        quotation_line.tax_included
                    ),
                    "lead_time_days": (
                        quotation_line.lead_time_days
                    ),
                    "brand_model": (
                        quotation_line.brand_model
                    ),
                    "payment_type": (
                        quotation_line.payment_type
                    ),
                    "payment_term_months": (
                        quotation_line.payment_term_months
                    ),
                    "origin_type": (
                        quotation_line.origin_type
                    ),
                    "notes": quotation_line.notes,
                    "status": quotation_line.status,
                    "is_selectable": is_selectable,
                    "is_selected": is_selected,
                    "selection_status": (
                        selected_candidate.status
                        if is_selected
                        else None
                    ),
                    "is_selection_locked": bool(
                        is_selected
                        and selected_candidate.status
                        == "USED"
                    ),
                    "is_best_price": False,
                },
            }

            cells.append(cell)
            calculated_cells.append(cell)

        has_mixed_currencies = (
            len(line_currency_codes) > 1
        )

        if calculated_cells:
            cells_by_currency: dict[
                str,
                list[dict],
            ] = {}

            for cell in calculated_cells:
                currency_code = (
                    cell["quotation"][
                        "currency_code"
                    ]
                )

                cells_by_currency.setdefault(
                    currency_code,
                    [],
                ).append(cell)

            for currency_cells in (
                cells_by_currency.values()
            ):
                minimum_unit_total = min(
                    cell["quotation"][
                        "unit_total"
                    ]
                    for cell in currency_cells
                )

                for cell in currency_cells:
                    cell["quotation"][
                        "is_best_price"
                    ] = (
                        cell["quotation"][
                            "unit_total"
                        ]
                        == minimum_unit_total
                    )

        selected_is_latest = False

        if selected_quotation_data:
            latest_selected_supplier = (
                latest_quotation_map.get(
                    (
                        request_line.id,
                        selected_quotation_data[
                            "supplier_id"
                        ],
                    )
                )
            )

            selected_is_latest = bool(
                latest_selected_supplier
                and latest_selected_supplier[0].id
                == selected_quotation_data[
                    "quotation_line_id"
                ]
            )

        matrix_lines.append(
            {
                "purchase_request_line_id": (
                    request_line.id
                ),
                "article_id": (
                    request_line.article_id
                ),
                "pending_article_id": (
                    request_line.pending_article_id
                ),
                "item_type": item_type,
                "item_id": item_id,
                "item_code": item_code,
                "item_name": item_name,
                "quantity_requested": (
                    quantity_requested
                ),
                "unit_id": request_line.unit_id,
                "unit": request_line.unit,
                "line_notes": (
                    request_line.line_notes
                ),
                "line_status": (
                    request_line.line_status
                ),
                "is_urgent": bool(
                    request_line.is_urgent
                ),
                "category_id": category_id,
                "category_code": category_id,
                "category_label": category_label,
                "cells": cells,
                "has_quotations": bool(
                    calculated_cells
                ),
                "quotation_count": len(
                    calculated_cells
                ),
                "currency_codes": sorted(
                    line_currency_codes
                ),
                "has_mixed_currencies": (
                    has_mixed_currencies
                ),
                "selected_candidate": (
                    selected_candidate
                ),
                "selected_quotation": (
                    selected_quotation_data
                ),
                "has_selection": bool(
                    selected_candidate
                ),
                "selection_status": (
                    selected_candidate.status
                    if selected_candidate
                    else None
                ),
                "is_selection_locked": bool(
                    selected_candidate
                    and selected_candidate.status
                    == "USED"
                ),
                "selected_is_latest": (
                    selected_is_latest
                ),
            }
        )

    return {
        "purchase_request_id": purchase_request.id,
        "purchase_request_number": (
            purchase_request.number
        ),
        "purchase_request_status": (
            purchase_request.status
        ),
        "purchase_request": purchase_request,
        "category_id": category_id,
        "category_code": category_id,
        "category_label": category_label,
        "quotation_category": quotation_category,
        "is_uncategorized": category_id is None,
        "suppliers": suppliers,
        "lines": matrix_lines,
        "total_lines": len(matrix_lines),
        "total_suppliers": len(suppliers),
        "total_quotations": total_quotations,
        "selected_lines": selected_lines,
        "pending_selection_lines": (
            len(matrix_lines)
            - selected_lines
        ),
    }

def get_purchase_order_candidate_for_request_line(
    *,
    purchase_request_line_id: int,
    include_cancelled: bool = False,
) -> PurchaseOrderCandidate | None:
    """
    Devuelve la selección de cotización correspondiente a una línea
    de solicitud.

    Por defecto no devuelve selecciones canceladas.
    """

    query = PurchaseOrderCandidate.query.filter(
        PurchaseOrderCandidate.purchase_request_line_id
        == purchase_request_line_id
    )

    if not include_cancelled:
        query = query.filter(
            PurchaseOrderCandidate.status.in_(
                {"PENDING", "USED"}
            )
        )

    return query.first()

def select_quotation_for_purchase_order(
    *,
    purchase_request_line_id: int,
    quotation_line_id: int,
    selected_by_user_id: int,
) -> PurchaseOrderCandidate:
    """
    Selecciona manualmente la cotización ganadora de una línea
    de solicitud y la deja pendiente para generar una OC.

    Reglas:
    - la cotización debe pertenecer a la línea indicada;
    - no se puede seleccionar una cotización descartada;
    - no se puede seleccionar una cotización en borrador;
    - solo existe una selección por línea de solicitud;
    - una selección ya utilizada en una OC no puede modificarse;
    - cambiar de proveedor actualiza el mismo candidato pendiente.
    """

    if not selected_by_user_id:
        raise QuotationServiceError(
            "No se pudo identificar el usuario que realiza la selección."
        )

    request_line = _get_purchase_request_line_or_error(
        purchase_request_line_id
    )

    quotation_line = (
        QuotationLine.query
        .filter(
            QuotationLine.id == quotation_line_id,
            QuotationLine.purchase_request_line_id
            == purchase_request_line_id,
        )
        .with_for_update()
        .first()
    )

    if not quotation_line:
        raise QuotationServiceError(
            "La cotización indicada no pertenece a esta línea "
            "de solicitud de compra."
        )

    if quotation_line.status == "DESCARTADA":
        raise QuotationServiceError(
            "No se puede aprobar una cotización descartada."
        )

    if quotation_line.status == "BORRADOR":
        raise QuotationServiceError(
            "No se puede aprobar una cotización que todavía "
            "se encuentra en borrador."
        )

    if quotation_line.status == "CONVERTIDA_A_OC":
        raise QuotationServiceError(
            "Esta cotización ya fue convertida en una orden de compra."
        )

    if quotation_line.unit_price is None:
        raise QuotationServiceError(
            "La cotización seleccionada no tiene precio unitario."
        )

    quoted_price = Decimal(
        str(quotation_line.unit_price or 0)
    )

    if quoted_price <= 0:
        raise QuotationServiceError(
            "La cotización seleccionada debe tener un precio "
            "unitario mayor que cero."
        )

    existing_candidate = (
        PurchaseOrderCandidate.query
        .filter(
            PurchaseOrderCandidate.purchase_request_line_id
            == purchase_request_line_id
        )
        .with_for_update()
        .first()
    )

    if (
        existing_candidate
        and existing_candidate.status == "USED"
    ):
        raise QuotationServiceError(
            "La cotización aprobada de esta línea ya fue utilizada "
            "en una orden de compra y no puede cambiarse."
        )

    candidate_using_quotation = (
        PurchaseOrderCandidate.query
        .filter(
            PurchaseOrderCandidate.quotation_line_id
            == quotation_line_id
        )
        .with_for_update()
        .first()
    )

    if (
        candidate_using_quotation
        and (
            not existing_candidate
            or candidate_using_quotation.id
            != existing_candidate.id
        )
    ):
        raise QuotationServiceError(
            "Esta cotización ya está asociada a otra selección de pre-OC."
        )

    now = datetime.now(UTC)

    if existing_candidate:
        existing_candidate.quotation_line_id = (
            quotation_line.id
        )
        existing_candidate.supplier_id = (
            quotation_line.supplier_id
        )
        existing_candidate.selected_by_user_id = (
            selected_by_user_id
        )
        existing_candidate.purchase_order_id = None
        existing_candidate.status = "PENDING"
        existing_candidate.selected_at = now
        existing_candidate.updated_at = now

        candidate = existing_candidate
    else:
        candidate = PurchaseOrderCandidate(
            purchase_request_line_id=request_line.id,
            quotation_line_id=quotation_line.id,
            supplier_id=quotation_line.supplier_id,
            selected_by_user_id=selected_by_user_id,
            purchase_order_id=None,
            status="PENDING",
            selected_at=now,
            created_at=now,
            updated_at=now,
        )

        db.session.add(candidate)

    db.session.commit()

    return candidate

def clear_quotation_selection(
    *,
    purchase_request_line_id: int,
    cancelled_by_user_id: int,
) -> PurchaseOrderCandidate:
    """
    Quita la aprobación de una cotización mientras todavía no haya
    sido utilizada en una orden de compra.

    La selección no se elimina físicamente; queda como CANCELLED
    para conservar trazabilidad.
    """

    if not cancelled_by_user_id:
        raise QuotationServiceError(
            "No se pudo identificar el usuario que cancela la selección."
        )

    candidate = (
        PurchaseOrderCandidate.query
        .filter(
            PurchaseOrderCandidate.purchase_request_line_id
            == purchase_request_line_id
        )
        .with_for_update()
        .first()
    )

    if not candidate:
        raise QuotationServiceError(
            "Esta línea no tiene una cotización aprobada."
        )

    if candidate.status == "USED":
        raise QuotationServiceError(
            "La cotización aprobada ya fue utilizada en una orden "
            "de compra y no puede quitarse."
        )

    if candidate.status == "CANCELLED":
        raise QuotationServiceError(
            "La selección ya se encuentra cancelada."
        )

    candidate.status = "CANCELLED"
    candidate.purchase_order_id = None
    candidate.selected_by_user_id = cancelled_by_user_id
    candidate.updated_at = datetime.now(UTC)

    db.session.commit()

    return candidate

def list_pending_purchase_order_candidates_by_supplier(
    *,
    supplier_id: int | None = None,
) -> list[dict]:
    """
    Lista las selecciones pendientes de OC agrupadas por proveedor.

    La categoría se obtiene mediante ArticleQuotationCategory.

    Las monedas no se suman entre sí. Cuando un proveedor posee
    candidatos en varias monedas, se generan totales separados.
    """

    query = (
        db.session.query(
            PurchaseOrderCandidate,
            QuotationLine,
            PurchaseRequestLine,
            PurchaseRequest,
            Supplier,
        )
        .join(
            QuotationLine,
            QuotationLine.id
            == PurchaseOrderCandidate.quotation_line_id,
        )
        .join(
            PurchaseRequestLine,
            PurchaseRequestLine.id
            == PurchaseOrderCandidate.purchase_request_line_id,
        )
        .join(
            PurchaseRequest,
            PurchaseRequest.id
            == PurchaseRequestLine.purchase_request_id,
        )
        .join(
            Supplier,
            Supplier.id
            == PurchaseOrderCandidate.supplier_id,
        )
        .filter(
            PurchaseOrderCandidate.status
            == "PENDING",
            PurchaseOrderCandidate.purchase_order_id.is_(
                None
            ),
        )
    )

    if supplier_id:
        query = query.filter(
            PurchaseOrderCandidate.supplier_id
            == supplier_id
        )

    rows = (
        query
        .order_by(
            Supplier.commercial_name.asc(),
            Supplier.legal_name.asc(),
            PurchaseRequest.number.asc(),
            PurchaseRequestLine.id.asc(),
        )
        .all()
    )

    if not rows:
        return []

    article_ids = {
        request_line.article_id
        for (
            candidate,
            quotation_line,
            request_line,
            purchase_request,
            supplier,
        ) in rows
        if request_line.article_id is not None
    }

    pending_article_ids = {
        request_line.pending_article_id
        for (
            candidate,
            quotation_line,
            request_line,
            purchase_request,
            supplier,
        ) in rows
        if request_line.pending_article_id is not None
    }

    assignment_filters = []

    if article_ids:
        assignment_filters.append(
            ArticleQuotationCategory.article_id.in_(
                article_ids
            )
        )

    if pending_article_ids:
        assignment_filters.append(
            ArticleQuotationCategory.pending_article_id.in_(
                pending_article_ids
            )
        )

    article_category_map: dict[int, dict] = {}
    pending_category_map: dict[int, dict] = {}

    if assignment_filters:
        assignment_rows = (
            db.session.query(
                ArticleQuotationCategory.article_id,
                ArticleQuotationCategory.pending_article_id,
                QuotationCategory.id.label(
                    "category_id"
                ),
                QuotationCategory.name.label(
                    "category_name"
                ),
            )
            .join(
                QuotationCategory,
                QuotationCategory.id
                == ArticleQuotationCategory.quotation_category_id,
            )
            .filter(
                db.or_(*assignment_filters)
            )
            .all()
        )

        for assignment_row in assignment_rows:
            category_data = {
                "id": assignment_row.category_id,
                "name": (
                    assignment_row.category_name
                    or "Sin categoría"
                ),
            }

            if assignment_row.article_id is not None:
                article_category_map[
                    assignment_row.article_id
                ] = category_data

            if (
                assignment_row.pending_article_id
                is not None
            ):
                pending_category_map[
                    assignment_row.pending_article_id
                ] = category_data

    supplier_groups: dict[int, dict] = {}

    for (
        candidate,
        quotation_line,
        request_line,
        purchase_request,
        supplier,
    ) in rows:
        current_supplier_id = supplier.id

        supplier_name = (
            supplier.commercial_name
            or supplier.legal_name
            or f"Proveedor {supplier.id}"
        )

        if (
            current_supplier_id
            not in supplier_groups
        ):
            supplier_groups[
                current_supplier_id
            ] = {
                "supplier_id": (
                    current_supplier_id
                ),
                "supplier_name": supplier_name,
                "currencies": set(),
                "has_mixed_currencies": False,
                "total_lines": 0,

                # Se conservan por compatibilidad cuando
                # solamente existe una moneda.
                "subtotal": Decimal("0"),
                "discount_amount": Decimal("0"),
                "tax_amount": Decimal("0"),
                "total": Decimal("0"),

                # Totales oficiales separados por moneda.
                "totals_by_currency": {},
                "lines": [],
            }

        group = supplier_groups[
            current_supplier_id
        ]

        quantity = _normalize_decimal(
            request_line.quantity_requested
            or Decimal("0"),
            "cantidad solicitada",
        )

        amounts = _calculate_quotation_amounts(
            quotation_line,
            quantity,
        )

        currency_code = (
            quotation_line.currency_code
            or "CRC"
        ).strip().upper()

        group["currencies"].add(
            currency_code
        )

        group["total_lines"] += 1

        currency_totals = (
            group["totals_by_currency"]
            .setdefault(
                currency_code,
                {
                    "currency_code": (
                        currency_code
                    ),
                    "subtotal": Decimal("0"),
                    "discount_amount": (
                        Decimal("0")
                    ),
                    "tax_amount": Decimal("0"),
                    "total": Decimal("0"),
                    "total_lines": 0,
                },
            )
        )

        currency_totals[
            "subtotal"
        ] += amounts["line_subtotal"]

        currency_totals[
            "discount_amount"
        ] += amounts[
            "line_discount_amount"
        ]

        currency_totals[
            "tax_amount"
        ] += amounts["line_tax_amount"]

        currency_totals[
            "total"
        ] += amounts["line_total"]

        currency_totals[
            "total_lines"
        ] += 1

        category_data = None

        if request_line.article_id is not None:
            category_data = (
                article_category_map.get(
                    request_line.article_id
                )
            )

        elif (
            request_line.pending_article_id
            is not None
        ):
            category_data = (
                pending_category_map.get(
                    request_line.pending_article_id
                )
            )

        group["lines"].append(
            {
                "candidate_id": candidate.id,
                "purchase_request_id": (
                    purchase_request.id
                ),
                "purchase_request_number": (
                    purchase_request.number
                ),
                "purchase_request_line_id": (
                    request_line.id
                ),
                "quotation_line_id": (
                    quotation_line.id
                ),
                "article_id": (
                    request_line.article_id
                ),
                "pending_article_id": (
                    request_line.pending_article_id
                ),
                "item_code": (
                    request_line.item_code or "-"
                ),
                "item_name": (
                    request_line.item_name
                    or "Sin artículo"
                ),
                "quotation_category_id": (
                    category_data["id"]
                    if category_data
                    else None
                ),

                # Se conservan ambas claves para no romper
                # templates existentes.
                "quotation_category": (
                    category_data["name"]
                    if category_data
                    else None
                ),
                "quotation_category_label": (
                    category_data["name"]
                    if category_data
                    else "Sin categoría"
                ),

                "quantity_requested": quantity,
                "unit_id": request_line.unit_id,
                "currency_code": currency_code,
                "unit_price": (
                    amounts["unit_price"]
                ),
                "unit_subtotal": (
                    amounts["unit_subtotal"]
                ),
                "discount_pct": (
                    amounts["discount_pct"]
                ),
                "discount_amount": (
                    amounts[
                        "line_discount_amount"
                    ]
                ),
                "tax_pct": amounts["tax_pct"],
                "tax_amount": (
                    amounts["line_tax_amount"]
                ),
                "line_subtotal": (
                    amounts["line_subtotal"]
                ),
                "line_total": (
                    amounts["line_total"]
                ),
                "tax_included": bool(
                    quotation_line.tax_included
                ),
                "payment_type": (
                    quotation_line.payment_type
                ),
                "payment_term_months": (
                    quotation_line.payment_term_months
                ),
                "origin_type": (
                    quotation_line.origin_type
                ),
                "lead_time_days": (
                    quotation_line.lead_time_days
                ),
                "brand_model": (
                    quotation_line.brand_model
                ),
                "notes": quotation_line.notes,
                "selected_at": (
                    candidate.selected_at
                ),
            }
        )

    result: list[dict] = []

    for group in supplier_groups.values():
        currencies = sorted(
            group["currencies"]
        )

        group["currencies"] = currencies
        group["currency_code"] = (
            currencies[0]
            if len(currencies) == 1
            else None
        )

        group["has_mixed_currencies"] = (
            len(currencies) > 1
        )

        group["totals_by_currency"] = [
            group["totals_by_currency"][
                currency_code
            ]
            for currency_code in currencies
        ]

        # Solo se genera un total general cuando
        # todas las líneas tienen la misma moneda.
        if len(currencies) == 1:
            only_totals = (
                group[
                    "totals_by_currency"
                ][0]
            )

            group["subtotal"] = (
                only_totals["subtotal"]
            )

            group["discount_amount"] = (
                only_totals[
                    "discount_amount"
                ]
            )

            group["tax_amount"] = (
                only_totals["tax_amount"]
            )

            group["total"] = (
                only_totals["total"]
            )
        else:
            group["subtotal"] = None
            group["discount_amount"] = None
            group["tax_amount"] = None
            group["total"] = None

        result.append(group)

    result.sort(
        key=lambda item: (
            item["supplier_name"].lower()
        )
    )

    return result

    return result

def get_pending_purchase_order_candidates_for_supplier(
    *,
    supplier_id: int,
    candidate_ids: list[int] | None = None,
) -> list[PurchaseOrderCandidate]:
    """
    Obtiene candidatos pendientes pertenecientes exclusivamente
    al proveedor indicado.

    Si candidate_ids tiene valores, devuelve únicamente esos registros.
    """

    if not supplier_id:
        raise QuotationServiceError(
            "Debe indicar un proveedor."
        )

    query = PurchaseOrderCandidate.query.filter(
        PurchaseOrderCandidate.supplier_id == supplier_id,
        PurchaseOrderCandidate.status == "PENDING",
        PurchaseOrderCandidate.purchase_order_id.is_(None),
    )

    if candidate_ids is not None:
        clean_ids: list[int] = []

        for candidate_id in candidate_ids:
            try:
                clean_ids.append(int(candidate_id))
            except (TypeError, ValueError) as exc:
                raise QuotationServiceError(
                    "Se recibió una selección de pre-OC inválida."
                ) from exc

        if not clean_ids:
            raise QuotationServiceError(
                "Debe seleccionar al menos una línea para crear la OC."
            )

        query = query.filter(
            PurchaseOrderCandidate.id.in_(clean_ids)
        )

    candidates = (
        query
        .order_by(
            PurchaseOrderCandidate.selected_at.asc(),
            PurchaseOrderCandidate.id.asc(),
        )
        .all()
    )

    if not candidates:
        raise QuotationServiceError(
            "El proveedor no tiene líneas pendientes para generar una OC."
        )

    if candidate_ids is not None:
        expected_ids = set(clean_ids)
        returned_ids = {
            candidate.id
            for candidate in candidates
        }

        missing_ids = expected_ids - returned_ids

        if missing_ids:
            raise QuotationServiceError(
                "Una o más líneas seleccionadas ya no están disponibles "
                "o pertenecen a otro proveedor."
            )

    return candidates

def get_registered_suppliers_for_article(
    article_id: int,
) -> list[Supplier]:
    return (
        Supplier.query
        .join(
            ArticleSupplier,
            ArticleSupplier.supplier_id
            == Supplier.id,
        )
        .filter(
            ArticleSupplier.article_id == article_id,
            ArticleSupplier.is_active.is_(True),
            Supplier.is_active.is_(True),
        )
        .order_by(
            Supplier.commercial_name.asc(),
            Supplier.legal_name.asc(),
        )
        .all()
    )


def get_available_suppliers_for_article(
    *,
    article_id: int,
    exclude_supplier_ids: list[int] | None = None,
) -> list[Supplier]:
    exclude_supplier_ids = (
        exclude_supplier_ids or []
    )

    query = (
        Supplier.query
        .join(
            ArticleSupplier,
            ArticleSupplier.supplier_id
            == Supplier.id,
        )
        .filter(
            ArticleSupplier.article_id == article_id,
            ArticleSupplier.is_active.is_(True),
            Supplier.is_active.is_(True),
        )
    )

    if exclude_supplier_ids:
        query = query.filter(
            Supplier.id.notin_(
                exclude_supplier_ids
            )
        )

    return (
        query
        .order_by(
            Supplier.commercial_name.asc(),
            Supplier.legal_name.asc(),
        )
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

def _get_best_quote_map_for_request_lines(
    request_lines: list[PurchaseRequestLine],
) -> dict[tuple[str, int], dict]:
    """
    Obtiene la mejor cotización histórica por artículo.

    Por cada artículo y proveedor conserva únicamente la cotización
    más reciente.

    Cuando existen distintas monedas para el mismo artículo, no se
    establece un único mejor precio global.
    """

    article_ids = {
        line.article_id
        for line in request_lines
        if getattr(
            line,
            "article_id",
            None,
        ) is not None
    }

    pending_article_ids = {
        line.pending_article_id
        for line in request_lines
        if getattr(
            line,
            "pending_article_id",
            None,
        ) is not None
    }

    if (
        not article_ids
        and not pending_article_ids
    ):
        return {}

    filters = []

    if article_ids:
        filters.append(
            QuotationLine.article_id.in_(
                article_ids
            )
        )

    if pending_article_ids:
        filters.append(
            QuotationLine.pending_article_id.in_(
                pending_article_ids
            )
        )

    rows = (
        db.session.query(
            QuotationLine,
            Supplier.commercial_name,
            Supplier.legal_name,
        )
        .join(
            Supplier,
            Supplier.id
            == QuotationLine.supplier_id,
        )
        .filter(
            QuotationLine.status
            != "DESCARTADA",
            db.or_(*filters),
        )
        .order_by(
            QuotationLine.article_id.asc(),
            QuotationLine.pending_article_id.asc(),
            QuotationLine.supplier_id.asc(),
            QuotationLine.quote_date.desc(),
            QuotationLine.created_at.desc(),
            QuotationLine.id.desc(),
        )
        .all()
    )

    processed_supplier_items: set[
        tuple[str, int, int]
    ] = set()

    quotations_by_item: dict[
        tuple[str, int],
        list[dict],
    ] = {}

    for (
        quotation_line,
        commercial_name,
        legal_name,
    ) in rows:
        if quotation_line.article_id is not None:
            item_key = (
                "ARTICLE",
                quotation_line.article_id,
            )

        elif (
            quotation_line.pending_article_id
            is not None
        ):
            item_key = (
                "PENDING",
                quotation_line.pending_article_id,
            )

        else:
            continue

        supplier_item_key = (
            item_key[0],
            item_key[1],
            quotation_line.supplier_id,
        )

        if (
            supplier_item_key
            in processed_supplier_items
        ):
            continue

        processed_supplier_items.add(
            supplier_item_key
        )

        amounts = _calculate_quotation_amounts(
            quotation_line,
            Decimal("1"),
        )

        currency_code = (
            quotation_line.currency_code
            or "CRC"
        ).strip().upper()

        quotations_by_item.setdefault(
            item_key,
            [],
        ).append(
            {
                "supplier_id": (
                    quotation_line.supplier_id
                ),
                "supplier_name": (
                    commercial_name
                    or legal_name
                    or "Proveedor"
                ),
                "last_price": (
                    amounts["unit_price"]
                ),
                "total_amount": (
                    amounts["unit_total"]
                ),
                "currency_code": (
                    currency_code
                ),
                "quotation_line_id": (
                    quotation_line.id
                ),
                "last_quote_date": (
                    quotation_line.quote_date
                ),
            }
        )

    best_quote_map: dict[
        tuple[str, int],
        dict,
    ] = {}

    for (
        item_key,
        quotations,
    ) in quotations_by_item.items():
        currencies = {
            quotation["currency_code"]
            for quotation in quotations
        }

        if len(currencies) != 1:
            best_quote_map[item_key] = {
                "supplier_id": None,
                "supplier_name": None,
                "last_price": None,
                "total_amount": None,
                "currency_code": None,
                "quotation_line_id": None,
                "last_quote_date": max(
                    (
                        quotation[
                            "last_quote_date"
                        ]
                        for quotation in quotations
                        if quotation[
                            "last_quote_date"
                        ] is not None
                    ),
                    default=None,
                ),
                "has_mixed_currencies": True,
                "currencies": sorted(
                    currencies
                ),
            }

            continue

        best_quotation = min(
            quotations,
            key=lambda quotation: (
                quotation["total_amount"],
                quotation["supplier_name"].lower(),
            ),
        )

        best_quote_map[item_key] = {
            **best_quotation,
            "has_mixed_currencies": False,
            "currencies": sorted(
                currencies
            ),
        }

    return best_quote_map

def list_quotation_line_groups(
    search: str | None = None,
) -> list[dict]:
    search = (search or "").strip()

    query = (
        db.session.query(
            PurchaseRequestLine.id.label(
                "purchase_request_line_id"
            ),
            PurchaseRequestLine.article_id.label(
                "article_id"
            ),
            PurchaseRequestLine.pending_article_id.label(
                "pending_article_id"
            ),
            PurchaseRequestLine.item_code.label(
                "item_code"
            ),
            PurchaseRequestLine.item_name.label(
                "item_name"
            ),
            PurchaseRequestLine.line_status.label(
                "line_status"
            ),
            PurchaseRequestLine.quantity_requested.label(
                "quantity_requested"
            ),
            PurchaseRequest.number.label(
                "purchase_request_number"
            ),
            PurchaseRequest.id.label(
                "purchase_request_id"
            ),
            func.count(
                QuotationLine.id
            ).label("total_quotes"),
            func.sum(
                db.case(
                    (
                        QuotationLine.status == "BORRADOR",
                        1,
                    ),
                    else_=0,
                )
            ).label("draft_quotes"),
            func.sum(
                db.case(
                    (
                        QuotationLine.status == "COTIZADA",
                        1,
                    ),
                    else_=0,
                )
            ).label("confirmed_quotes"),
            func.max(
                QuotationLine.quote_date
            ).label("last_quote_date"),
        )
        .join(
            QuotationLine,
            QuotationLine.purchase_request_line_id
            == PurchaseRequestLine.id,
        )
        .join(
            PurchaseRequest,
            PurchaseRequest.id
            == PurchaseRequestLine.purchase_request_id,
        )
        .group_by(
            PurchaseRequestLine.id,
            PurchaseRequestLine.article_id,
            PurchaseRequestLine.pending_article_id,
            PurchaseRequestLine.item_code,
            PurchaseRequestLine.item_name,
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
                PurchaseRequestLine.item_code.ilike(
                    like_value
                ),
                PurchaseRequestLine.item_name.ilike(
                    like_value
                ),
                QuotationLine.currency_code.ilike(
                    like_value
                ),
            )
        )

    rows = (
        query
        .order_by(
            func.max(
                QuotationLine.quote_date
            ).desc(),
            PurchaseRequest.id.desc(),
            PurchaseRequestLine.id.desc(),
        )
        .all()
    )

    if not rows:
        return []

    # Se crean objetos temporales sencillos para enviar todos los artículos
    # al cargador masivo sin volver a consultar PurchaseRequestLine.
    request_lines_for_comparison = []

    for row in rows:
        request_lines_for_comparison.append(
            type(
                "QuotationRequestLineData",
                (),
                {
                    "article_id": row.article_id,
                    "pending_article_id": row.pending_article_id,
                },
            )()
        )

    best_quote_map = _get_best_quote_map_for_request_lines(
        request_lines_for_comparison
    )

    groups: list[dict] = []

    for row in rows:
        if row.article_id is not None:
            item_key = (
                "ARTICLE",
                row.article_id,
            )
        elif row.pending_article_id is not None:
            item_key = (
                "PENDING",
                row.pending_article_id,
            )
        else:
            item_key = None

        best = (
            best_quote_map.get(item_key)
            if item_key is not None
            else None
        )

        groups.append(
            {
                "purchase_request_id": (
                    row.purchase_request_id
                ),
                "purchase_request_number": (
                    row.purchase_request_number
                ),
                "purchase_request_line_id": (
                    row.purchase_request_line_id
                ),
                "item_code": row.item_code or "-",
                "item_name": (
                    row.item_name or "Sin artículo"
                ),
                "quantity_requested": (
                    row.quantity_requested
                ),
                "line_status": row.line_status,
                "total_quotes": int(
                    row.total_quotes or 0
                ),
                "draft_quotes": int(
                    row.draft_quotes or 0
                ),
                "confirmed_quotes": int(
                    row.confirmed_quotes or 0
                ),
                "best_price": (
                    best["last_price"]
                    if best
                    else None
                ),
                "best_supplier": (
                    best["supplier_name"]
                    if best
                    else None
                ),
                "last_quote_date": (
                    row.last_quote_date
                ),
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