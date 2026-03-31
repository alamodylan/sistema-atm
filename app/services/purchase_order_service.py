from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func

from app.extensions import db
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_approval import PurchaseOrderApproval
from app.models.purchase_order_line import PurchaseOrderLine


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


def create_purchase_order(
    *,
    supplier_id: int,
    generated_by_user_id: int,
    purchase_request_id: int | None,
    site_id: int | None,
    warehouse_id: int | None,
    payment_terms: str | None,
    currency_code: str,
    notes: str | None,
    lines: list[PurchaseOrderLinePayload],
) -> PurchaseOrder:
    if not lines:
        raise PurchaseOrderServiceError("La orden de compra debe incluir al menos una línea.")

    for line in lines:
        _validate_po_line(line)

    purchase_order = PurchaseOrder(
        number=_generate_purchase_order_number(),
        supplier_id=supplier_id,
        generated_by_user_id=generated_by_user_id,
        purchase_request_id=purchase_request_id,
        site_id=site_id,
        warehouse_id=warehouse_id,
        approval_status="BORRADOR",
        payment_terms=(payment_terms or "").strip() or None,
        currency_code=(currency_code or "CRC").strip() or "CRC",
        notes=(notes or "").strip() or None,
    )

    db.session.add(purchase_order)
    db.session.flush()

    for line in lines:
        po_line = PurchaseOrderLine(
            purchase_order_id=purchase_order.id,
            purchase_request_line_id=line.purchase_request_line_id,
            quotation_line_id=line.quotation_line_id,
            article_id=line.article_id,
            pending_article_id=line.pending_article_id,
            quantity_ordered=_normalize_decimal(line.quantity_ordered, "cantidad"),
            quantity_received=Decimal("0"),
            unit_id=line.unit_id,
            unit_cost=_normalize_decimal(line.unit_cost, "costo unitario"),
            discount_pct=_normalize_decimal(line.discount_pct, "descuento"),
            tax_pct=_normalize_decimal(line.tax_pct, "impuesto"),
            line_subtotal=_normalize_decimal(line.line_subtotal, "subtotal"),
            line_total=_normalize_decimal(line.line_total, "total"),
            line_notes=(line.line_notes or "").strip() or None,
        )
        db.session.add(po_line)

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

    return query.order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc()).all()


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