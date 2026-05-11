from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func

from app.extensions import db
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_approval import PurchaseOrderApproval
from app.models.purchase_order_line import PurchaseOrderLine
from datetime import datetime, UTC
from app.models.quotation_line import QuotationLine


class PurchaseOrderServiceError(Exception):
    pass


@dataclass
class PurchaseOrderLinePayload:
    quantity_ordered: Decimal
    unit_cost: Decimal
    article_id: int | None = None
    pending_article_id: int | None = None
    purchase_request_line_id: int | None = None
    quotation_line_id: int | None = None
    unit_id: int | None = None
    discount_pct: Decimal = Decimal("0")
    tax_pct: Decimal = Decimal("0")
    line_subtotal: Decimal = Decimal("0")
    line_total: Decimal = Decimal("0")
    line_notes: str | None = None


def _generate_purchase_order_number() -> str:
    max_id = db.session.query(func.max(PurchaseOrder.id)).scalar() or 0
    next_id = int(max_id) + 1
    return f"OC-{next_id:06d}"


def _normalize_decimal(value: Any, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise PurchaseOrderServiceError(f"Valor inválido para {field_name}.") from exc


def _validate_po_line(line: PurchaseOrderLinePayload) -> None:
    if bool(line.article_id) == bool(line.pending_article_id):
        raise PurchaseOrderServiceError(
            "Cada línea de orden de compra debe tener un artículo normal o un artículo pendiente, pero no ambos."
        )

    if _normalize_decimal(line.quantity_ordered, "cantidad") <= 0:
        raise PurchaseOrderServiceError("La cantidad ordenada debe ser mayor que cero.")


def _validate_unique_quotation_usage(line: PurchaseOrderLinePayload) -> None:
    if not line.quotation_line_id:
        return

    existing = PurchaseOrderLine.query.filter(
        PurchaseOrderLine.quotation_line_id == line.quotation_line_id
    ).first()

    if existing:
        raise PurchaseOrderServiceError(
            "Una línea de cotización ya fue utilizada en otra orden de compra."
        )


def _validate_unique_request_usage(line: PurchaseOrderLinePayload) -> None:
    if not line.purchase_request_line_id:
        return

    existing = PurchaseOrderLine.query.filter(
        PurchaseOrderLine.purchase_request_line_id == line.purchase_request_line_id
    ).first()

    if existing:
        raise PurchaseOrderServiceError(
            "Esta línea de solicitud de compra ya fue utilizada en una orden."
        )


def create_purchase_order(
    *,
    supplier_id: int | None,
    generated_by_user_id: int,
    purchase_request_id: int | None = None,
    site_id: int | None = None,
    warehouse_id: int | None = None,
    payment_terms: str | None = None,
    currency_code: str = "CRC",
    notes: str | None = None,
    lines: list[PurchaseOrderLinePayload] | None = None,
) -> PurchaseOrder:
    if not supplier_id:
        raise PurchaseOrderServiceError("Debe seleccionar un proveedor.")

    if not generated_by_user_id:
        raise PurchaseOrderServiceError("No se pudo identificar el usuario que genera la orden.")

    lines = lines or []

    if not lines:
        raise PurchaseOrderServiceError("La orden de compra debe tener al menos una línea.")

    now = datetime.now(UTC)

    purchase_order = PurchaseOrder(
        number=_generate_purchase_order_number(),
        purchase_request_id=purchase_request_id,
        supplier_id=supplier_id,
        site_id=site_id,
        warehouse_id=warehouse_id,
        generated_by_user_id=generated_by_user_id,
        approval_status="PENDIENTE_APROBACION",
        submitted_for_approval_at=now,
        payment_terms=payment_terms,
        currency_code=currency_code or "CRC",
        notes=notes,
    )

    db.session.add(purchase_order)
    db.session.flush()

    for index, payload in enumerate(lines, start=1):
        if not payload.quantity_ordered or payload.quantity_ordered <= 0:
            raise PurchaseOrderServiceError(
                f"La cantidad de la línea {index} debe ser mayor a cero."
            )

        quantity = Decimal(str(payload.quantity_ordered))

        article_id = payload.article_id
        pending_article_id = payload.pending_article_id
        purchase_request_line_id = payload.purchase_request_line_id
        quotation_line_id = payload.quotation_line_id
        unit_id = payload.unit_id

        unit_cost = Decimal(str(payload.unit_cost or 0))
        discount_pct = Decimal(str(payload.discount_pct or 0))
        tax_pct = Decimal(str(payload.tax_pct or 0))
        line_subtotal = Decimal(str(payload.line_subtotal or 0))
        line_total = Decimal(str(payload.line_total or 0))

        if quotation_line_id:
            quotation_line = QuotationLine.query.get(quotation_line_id)

            if not quotation_line:
                raise PurchaseOrderServiceError(
                    f"La cotización de la línea {index} no existe."
                )

            if quotation_line.supplier_id != supplier_id:
                raise PurchaseOrderServiceError(
                    f"La línea {index} pertenece a otro proveedor. "
                    "Una orden de compra solo puede contener líneas del mismo proveedor."
                )

            article_id = quotation_line.article_id
            pending_article_id = quotation_line.pending_article_id
            purchase_request_line_id = quotation_line.purchase_request_line_id

            if not unit_id:
                if quotation_line.article and quotation_line.article.unit_id:
                    unit_id = quotation_line.article.unit_id
                elif quotation_line.purchase_request_line and quotation_line.purchase_request_line.unit_id:
                    unit_id = quotation_line.purchase_request_line.unit_id

            quoted_price = Decimal(str(quotation_line.unit_price or 0))
            discount_pct = Decimal(str(quotation_line.discount_pct or 0))
            tax_pct = Decimal(str(quotation_line.tax_pct or 0))

            if quoted_price <= 0:
                raise PurchaseOrderServiceError(
                    f"La cotización de la línea {index} no tiene un precio válido."
                )

            tax_factor = Decimal("1") + (tax_pct / Decimal("100"))

            if quotation_line.tax_included:
                subtotal_unit = (
                    quoted_price / tax_factor
                ) if tax_pct > 0 else quoted_price
            else:
                subtotal_unit = quoted_price

            discount_amount_unit = subtotal_unit * (discount_pct / Decimal("100"))
            taxable_base_unit = subtotal_unit - discount_amount_unit
            tax_amount_unit = taxable_base_unit * (tax_pct / Decimal("100"))
            total_unit = taxable_base_unit + tax_amount_unit

            unit_cost = taxable_base_unit
            line_subtotal = quantity * subtotal_unit
            line_total = quantity * total_unit

        else:
            if not line_subtotal:
                line_subtotal = quantity * unit_cost

            discount_amount = line_subtotal * (discount_pct / Decimal("100"))
            taxable_base = line_subtotal - discount_amount

            if tax_pct:
                line_total = taxable_base * (
                    Decimal("1") + (tax_pct / Decimal("100"))
                )
            else:
                line_total = taxable_base

        purchase_order_line = PurchaseOrderLine(
            purchase_order_id=purchase_order.id,
            purchase_request_line_id=purchase_request_line_id,
            quotation_line_id=quotation_line_id,
            article_id=article_id,
            pending_article_id=pending_article_id,
            quantity_ordered=quantity,
            quantity_received=Decimal("0"),
            unit_id=unit_id,
            unit_cost=unit_cost,
            discount_pct=discount_pct,
            tax_pct=tax_pct,
            line_subtotal=line_subtotal,
            line_total=line_total,
            line_notes=payload.line_notes,
        )

        db.session.add(purchase_order_line)

    db.session.commit()

    return purchase_order


def list_purchase_orders(
    *,
    approval_status: str | None = None,
    supplier_id: int | None = None,
    search: str | None = None,
) -> list[PurchaseOrder]:
    query = PurchaseOrder.query

    if approval_status:
        query = query.filter(PurchaseOrder.approval_status == approval_status)

    if supplier_id:
        query = query.filter(PurchaseOrder.supplier_id == supplier_id)

    if search:
        like_value = f"%{search.strip()}%"
        query = query.filter(PurchaseOrder.number.ilike(like_value))

    return query.order_by(
        PurchaseOrder.created_at.desc(),
        PurchaseOrder.id.desc()
    ).all()


def get_purchase_order_or_404(order_id: int) -> PurchaseOrder:
    return PurchaseOrder.query.get_or_404(order_id)


def register_purchase_order_approval(
    *,
    purchase_order_id: int,
    approved_by_user_id: int | None,
    status: str,
    reason: str | None,
) -> PurchaseOrderApproval:
    valid_statuses = {"APROBADA", "RECHAZADA"}
    if status not in valid_statuses:
        raise PurchaseOrderServiceError("Estado de aprobación inválido.")

    purchase_order = get_purchase_order_or_404(purchase_order_id)
    purchase_order.approval_status = status

    approval = PurchaseOrderApproval(
        purchase_order_id=purchase_order_id,
        approved_by_user_id=approved_by_user_id,
        status=status,
        reason=(reason or "").strip() or None,
    )

    db.session.add(approval)
    db.session.commit()
    return approval

def adjust_approved_purchase_order_line(
    *,
    purchase_order_line_id: int,
    new_quantity: Any,
    new_unit_cost: Any,
) -> PurchaseOrderLine:

    purchase_order_line = PurchaseOrderLine.query.get(
        purchase_order_line_id
    )

    if not purchase_order_line:
        raise PurchaseOrderServiceError(
            "La línea de orden de compra no existe."
        )

    purchase_order = purchase_order_line.purchase_order

    if purchase_order.approval_status != "APROBADA":
        raise PurchaseOrderServiceError(
            "Solo se pueden ajustar órdenes aprobadas."
        )

    original_quantity = Decimal(
        str(purchase_order_line.quantity_ordered or 0)
    )

    original_unit_cost = Decimal(
        str(purchase_order_line.unit_cost or 0)
    )

    quantity = _normalize_decimal(
        new_quantity,
        "cantidad"
    )

    unit_cost = _normalize_decimal(
        new_unit_cost,
        "precio unitario"
    )

    if quantity <= 0:
        raise PurchaseOrderServiceError(
            "La cantidad debe ser mayor que cero."
        )

    if unit_cost <= 0:
        raise PurchaseOrderServiceError(
            "El precio unitario debe ser mayor que cero."
        )

    if quantity > original_quantity:
        raise PurchaseOrderServiceError(
            "No se puede aumentar la cantidad aprobada."
        )

    if unit_cost > original_unit_cost:
        raise PurchaseOrderServiceError(
            "No se puede aumentar el precio unitario aprobado."
        )

    discount_pct = Decimal(
        str(purchase_order_line.discount_pct or 0)
    )

    tax_pct = Decimal(
        str(purchase_order_line.tax_pct or 0)
    )

    line_subtotal = quantity * unit_cost

    discount_amount = (
        line_subtotal * (discount_pct / Decimal("100"))
    )

    taxable_base = (
        line_subtotal - discount_amount
    )

    tax_amount = (
        taxable_base * (tax_pct / Decimal("100"))
    )

    line_total = taxable_base + tax_amount

    purchase_order_line.quantity_ordered = quantity
    purchase_order_line.unit_cost = unit_cost
    purchase_order_line.line_subtotal = line_subtotal
    purchase_order_line.line_total = line_total

    db.session.commit()

    return purchase_order_line