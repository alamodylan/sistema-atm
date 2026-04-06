from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func

from app.extensions import db
from app.models.inventory_entry import InventoryEntry
from app.models.inventory_entry_line import InventoryEntryLine
from app.models.pending_article import PendingArticle
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_line import PurchaseOrderLine
from app.models.warehouse import Warehouse
from app.services.inventory_service import add_stock


class InventoryEntryServiceError(Exception):
    pass


@dataclass
class InventoryEntryLinePayload:
    quantity_received: Decimal
    article_id: int | None = None
    pending_article_id: int | None = None
    purchase_order_line_id: int | None = None
    warehouse_location_id: int | None = None
    unit_id: int | None = None
    unit_cost_without_tax: Decimal = Decimal("0")
    unit_cost_with_tax: Decimal = Decimal("0")
    discount_pct: Decimal = Decimal("0")
    tax_pct: Decimal = Decimal("0")
    line_notes: str | None = None


def _generate_inventory_entry_number() -> str:
    max_id = db.session.query(func.max(InventoryEntry.id)).scalar() or 0
    next_id = int(max_id) + 1
    return f"ENT-{next_id:06d}"


def _normalize_decimal(value: Any, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise InventoryEntryServiceError(f"Valor inválido para {field_name}.") from exc


def _resolve_site_id(warehouse_id: int, site_id: int | None) -> int | None:
    if site_id:
        return site_id

    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        raise InventoryEntryServiceError("La bodega seleccionada no existe.")

    return warehouse.site_id


def _validate_entry_line(line: InventoryEntryLinePayload) -> None:
    if bool(line.article_id) == bool(line.pending_article_id):
        raise InventoryEntryServiceError(
            "Cada línea de entrada debe tener un artículo normal o un artículo pendiente, pero no ambos."
        )

    if not line.purchase_order_line_id:
        raise InventoryEntryServiceError(
            "Cada línea de entrada debe estar ligada a una línea de la orden de compra."
        )

    if _normalize_decimal(line.quantity_received, "cantidad recibida") <= 0:
        raise InventoryEntryServiceError("La cantidad recibida debe ser mayor que cero.")


def _validate_purchase_order_line_pending_quantity(
    *,
    purchase_order_id: int,
    purchase_order_line_id: int,
    quantity_received: Decimal,
    article_id: int | None,
    pending_article_id: int | None,
) -> PurchaseOrderLine:
    po_line = PurchaseOrderLine.query.get(purchase_order_line_id)
    if not po_line:
        raise InventoryEntryServiceError("La línea de orden de compra indicada no existe.")

    if int(po_line.purchase_order_id) != int(purchase_order_id):
        raise InventoryEntryServiceError(
            "La línea seleccionada no pertenece a la orden de compra indicada."
        )

    if bool(po_line.article_id) != bool(article_id):
        raise InventoryEntryServiceError(
            "El tipo de artículo de la línea no coincide con la línea de la orden de compra."
        )

    if bool(po_line.pending_article_id) != bool(pending_article_id):
        raise InventoryEntryServiceError(
            "El tipo de artículo pendiente de la línea no coincide con la línea de la orden de compra."
        )

    if po_line.article_id and int(po_line.article_id) != int(article_id):
        raise InventoryEntryServiceError(
            "El artículo de la entrada no coincide con el artículo de la línea de la orden."
        )

    if po_line.pending_article_id and int(po_line.pending_article_id) != int(pending_article_id):
        raise InventoryEntryServiceError(
            "El artículo pendiente de la entrada no coincide con el de la línea de la orden."
        )

    ordered = Decimal(str(po_line.quantity_ordered or 0))
    already_received = Decimal(str(po_line.quantity_received or 0))
    pending = ordered - already_received

    if pending <= 0:
        raise InventoryEntryServiceError(
            "La línea seleccionada ya no tiene cantidad pendiente por recibir."
        )

    if quantity_received > pending:
        raise InventoryEntryServiceError(
            f"La cantidad recibida ({quantity_received}) excede lo pendiente ({pending}) en la línea de la orden."
        )

    return po_line


def _validate_line_cost_consistency(
    *,
    unit_cost_without_tax: Decimal,
    unit_cost_with_tax: Decimal,
    discount_pct: Decimal,
    tax_pct: Decimal,
) -> None:
    if unit_cost_without_tax < 0:
        raise InventoryEntryServiceError("El costo unitario sin impuesto no puede ser negativo.")

    if unit_cost_with_tax < 0:
        raise InventoryEntryServiceError("El costo unitario con impuesto no puede ser negativo.")

    if discount_pct < 0:
        raise InventoryEntryServiceError("El descuento no puede ser negativo.")

    if tax_pct < 0:
        raise InventoryEntryServiceError("El impuesto no puede ser negativo.")

    net_without_tax = unit_cost_without_tax * (Decimal("1") - (discount_pct / Decimal("100")))
    expected_with_tax = net_without_tax * (Decimal("1") + (tax_pct / Decimal("100")))

    if abs(expected_with_tax - unit_cost_with_tax) > Decimal("0.01"):
        raise InventoryEntryServiceError(
            "El costo con impuesto no coincide con el porcentaje de impuesto y descuento indicado."
        )


def _refresh_purchase_order_receipt_status(purchase_order_id: int) -> None:
    purchase_order = PurchaseOrder.query.get(purchase_order_id)
    if not purchase_order:
        return

    lines = purchase_order.lines or []
    if not lines:
        return

    all_fully_received = True
    any_received = False
    any_line_exists = False

    for line in lines:
        any_line_exists = True
        ordered = Decimal(str(line.quantity_ordered or 0))
        received = Decimal(str(line.quantity_received or 0))

        if received > 0:
            any_received = True

        if received < ordered:
            all_fully_received = False

    if not any_line_exists:
        return

    if all_fully_received:
        purchase_order.approval_status = "RECIBIDA_TOTAL"
    elif any_received:
        purchase_order.approval_status = "RECIBIDA_PARCIAL"
    elif purchase_order.approval_status not in {"RECHAZADA", "ANULADA"}:
        purchase_order.approval_status = "APROBADA"


def create_inventory_entry(
    *,
    purchase_order_id: int,
    supplier_id: int,
    warehouse_id: int,
    entered_by_user_id: int,
    invoice_number: str,
    invoice_date,
    notes: str | None,
    lines: list[InventoryEntryLinePayload],
    site_id: int | None = None,
) -> InventoryEntry:
    if not purchase_order_id:
        raise InventoryEntryServiceError("La orden de compra es obligatoria.")

    if not supplier_id:
        raise InventoryEntryServiceError("El proveedor es obligatorio.")

    if not warehouse_id:
        raise InventoryEntryServiceError("La bodega destino es obligatoria.")

    if not lines:
        raise InventoryEntryServiceError(
            "La entrada a inventario debe incluir al menos una línea."
        )

    purchase_order = PurchaseOrder.query.get(purchase_order_id)
    if not purchase_order:
        raise InventoryEntryServiceError("La orden de compra seleccionada no existe.")

    if purchase_order.approval_status not in {"APROBADA", "RECIBIDA_PARCIAL"}:
        raise InventoryEntryServiceError(
            "Solo se pueden registrar entradas para órdenes aprobadas o parcialmente recibidas."
        )

    if not purchase_order.supplier_id:
        raise InventoryEntryServiceError(
            "La orden de compra seleccionada no tiene proveedor asociado."
        )

    if int(supplier_id) != int(purchase_order.supplier_id):
        raise InventoryEntryServiceError(
            "El proveedor de la entrada debe coincidir con el proveedor de la orden de compra."
        )

    invoice_number = (invoice_number or "").strip()
    if not invoice_number:
        raise InventoryEntryServiceError("El número de factura es obligatorio.")

    resolved_site_id = _resolve_site_id(warehouse_id, site_id)

    for line in lines:
        _validate_entry_line(line)

    inventory_entry = InventoryEntry(
        number=_generate_inventory_entry_number(),
        purchase_order_id=purchase_order_id,
        supplier_id=supplier_id,
        warehouse_id=warehouse_id,
        site_id=resolved_site_id,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        entered_by_user_id=entered_by_user_id,
        notes=(notes or "").strip() or None,
    )

    db.session.add(inventory_entry)
    db.session.flush()

    for line in lines:
        quantity_received = _normalize_decimal(
            line.quantity_received,
            "cantidad recibida",
        )
        unit_cost_without_tax = _normalize_decimal(
            line.unit_cost_without_tax,
            "costo sin impuesto",
        )
        unit_cost_with_tax = _normalize_decimal(
            line.unit_cost_with_tax,
            "costo con impuesto",
        )
        discount_pct = _normalize_decimal(line.discount_pct, "descuento")
        tax_pct = _normalize_decimal(line.tax_pct, "impuesto")

        _validate_line_cost_consistency(
            unit_cost_without_tax=unit_cost_without_tax,
            unit_cost_with_tax=unit_cost_with_tax,
            discount_pct=discount_pct,
            tax_pct=tax_pct,
        )

        po_line = _validate_purchase_order_line_pending_quantity(
            purchase_order_id=purchase_order_id,
            purchase_order_line_id=line.purchase_order_line_id,
            quantity_received=quantity_received,
            article_id=line.article_id,
            pending_article_id=line.pending_article_id,
        )

        entry_line = InventoryEntryLine(
            inventory_entry_id=inventory_entry.id,
            purchase_order_line_id=line.purchase_order_line_id,
            article_id=line.article_id,
            pending_article_id=line.pending_article_id,
            warehouse_location_id=line.warehouse_location_id,
            quantity_received=quantity_received,
            unit_id=line.unit_id,
            unit_cost_without_tax=unit_cost_without_tax,
            unit_cost_with_tax=unit_cost_with_tax,
            discount_pct=discount_pct,
            tax_pct=tax_pct,
            line_notes=(line.line_notes or "").strip() or None,
        )
        db.session.add(entry_line)

        po_line.quantity_received = Decimal(
            str(po_line.quantity_received or 0)
        ) + quantity_received

        resolved_article_id = None

        if line.article_id:
            resolved_article_id = line.article_id

        elif line.pending_article_id:
            pending_article = PendingArticle.query.get(line.pending_article_id)
            if not pending_article:
                raise InventoryEntryServiceError(
                    "El artículo pendiente indicado no existe."
                )

            if pending_article.linked_article_id:
                resolved_article_id = pending_article.linked_article_id

        if resolved_article_id:
            add_stock(
                article_id=resolved_article_id,
                warehouse_id=warehouse_id,
                quantity=quantity_received,
                performed_by_user_id=entered_by_user_id,
                movement_type="ENTRADA_COMPRA",
                reason=f"Entrada por compra {inventory_entry.number}",
                reference_type="INVENTORY_ENTRY",
                reference_id=inventory_entry.id,
                reference_number=inventory_entry.number,
                unit_cost=unit_cost_without_tax,
                warehouse_location_id=line.warehouse_location_id,
                commit=False,
            )

    _refresh_purchase_order_receipt_status(purchase_order_id)
    db.session.commit()
    return inventory_entry


def list_inventory_entries(search: str | None = None) -> list[InventoryEntry]:
    query = InventoryEntry.query

    if search:
        like_value = f"%{search.strip()}%"
        query = query.filter(
            db.or_(
                InventoryEntry.number.ilike(like_value),
                InventoryEntry.invoice_number.ilike(like_value),
            )
        )

    return query.order_by(
        InventoryEntry.created_at.desc(),
        InventoryEntry.id.desc(),
    ).all()


def get_inventory_entry_or_404(entry_id: int) -> InventoryEntry:
    return InventoryEntry.query.get_or_404(entry_id)