from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models.article import Article
from app.models.inventory import InventoryLedger, WarehouseLocationStock, WarehouseStock
from app.models.warehouse import Warehouse
from app.services.audit_service import log_action


class InventoryServiceError(Exception):
    pass


def _to_decimal(value: Decimal | int | float | str | None, field_name: str = "cantidad") -> Decimal:
    if value is None:
        raise InventoryServiceError(f"La {field_name} es obligatoria.")

    try:
        qty = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise InventoryServiceError(f"La {field_name} no tiene un formato válido.")

    return qty


def _validate_positive(value: Decimal, message: str) -> None:
    if value <= 0:
        raise InventoryServiceError(message)


def get_warehouse_stock_record(article_id: int, warehouse_id: int) -> WarehouseStock | None:
    return WarehouseStock.query.filter_by(
        article_id=article_id,
        warehouse_id=warehouse_id,
    ).first()


def get_or_create_warehouse_stock_record(article_id: int, warehouse_id: int) -> WarehouseStock:
    record = get_warehouse_stock_record(article_id, warehouse_id)

    if record:
        return record

    record = WarehouseStock(
        article_id=article_id,
        warehouse_id=warehouse_id,
        quantity_on_hand=Decimal("0.00"),
        reserved_quantity=Decimal("0.00"),
    )
    db.session.add(record)
    db.session.flush()

    return record


def get_location_stock_record(article_id: int, warehouse_location_id: int) -> WarehouseLocationStock | None:
    return WarehouseLocationStock.query.filter_by(
        article_id=article_id,
        warehouse_location_id=warehouse_location_id,
    ).first()


def get_or_create_location_stock_record(article_id: int, warehouse_location_id: int) -> WarehouseLocationStock:
    record = get_location_stock_record(article_id, warehouse_location_id)

    if record:
        return record

    record = WarehouseLocationStock(
        article_id=article_id,
        warehouse_location_id=warehouse_location_id,
        quantity_on_hand=Decimal("0.00"),
    )
    db.session.add(record)
    db.session.flush()

    return record


def create_inventory_ledger_entry(
    *,
    movement_type: str,
    warehouse_id: int,
    article_id: int,
    quantity_change: Decimal,
    performed_by_user_id: int | None,
    related_warehouse_id: int | None = None,
    warehouse_location_id: int | None = None,
    unit_cost: Decimal | None = None,
    total_cost: Decimal | None = None,
    reference_type: str | None = None,
    reference_id: int | None = None,
    reference_number: str | None = None,
    notes: str | None = None,
) -> InventoryLedger:
    entry = InventoryLedger(
        movement_type=movement_type,
        warehouse_id=warehouse_id,
        related_warehouse_id=related_warehouse_id,
        warehouse_location_id=warehouse_location_id,
        article_id=article_id,
        quantity_change=quantity_change,
        unit_cost=unit_cost,
        total_cost=total_cost,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_number=reference_number,
        notes=notes,
        performed_by_user_id=performed_by_user_id,
    )
    db.session.add(entry)
    db.session.flush()
    return entry


def add_stock(
    *,
    article_id: int,
    warehouse_id: int,
    quantity: Decimal | int | float | str,
    performed_by_user_id: int | None,
    movement_type: str = "AJUSTE_MANUAL",
    reason: str = "Entrada manual",
    reference_type: str | None = None,
    reference_id: int | None = None,
    reference_number: str | None = None,
    unit_cost: Decimal | int | float | str | None = None,
    warehouse_location_id: int | None = None,
    commit: bool = True,
) -> WarehouseStock:
    qty = _to_decimal(quantity)
    _validate_positive(qty, "La cantidad a sumar debe ser mayor a 0.")

    article = Article.query.get(article_id)
    if not article:
        raise InventoryServiceError("El artículo no existe.")

    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        raise InventoryServiceError("La bodega no existe.")

    record = get_or_create_warehouse_stock_record(article_id, warehouse_id)

    previous_qty = Decimal(str(record.quantity_on_hand or 0))
    record.quantity_on_hand = previous_qty + qty

    if warehouse_location_id:
        location_record = get_or_create_location_stock_record(article_id, warehouse_location_id)
        location_record.quantity_on_hand = Decimal(str(location_record.quantity_on_hand or 0)) + qty

    unit_cost_decimal = None
    total_cost_decimal = None
    if unit_cost is not None:
        unit_cost_decimal = _to_decimal(unit_cost, "costo unitario")
        total_cost_decimal = unit_cost_decimal * qty

        record.last_unit_cost = unit_cost_decimal

        if record.quantity_on_hand > 0:
            previous_avg = Decimal(str(record.avg_unit_cost or 0))
            new_total_qty = previous_qty + qty

            if new_total_qty > 0:
                previous_total_cost = previous_avg * previous_qty
                incoming_total_cost = unit_cost_decimal * qty
                record.avg_unit_cost = (previous_total_cost + incoming_total_cost) / new_total_qty
        else:
            record.avg_unit_cost = unit_cost_decimal

    ledger_entry = create_inventory_ledger_entry(
        movement_type=movement_type,
        warehouse_id=warehouse_id,
        article_id=article_id,
        quantity_change=qty,
        performed_by_user_id=performed_by_user_id,
        warehouse_location_id=warehouse_location_id,
        unit_cost=unit_cost_decimal,
        total_cost=total_cost_decimal,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_number=reference_number,
        notes=reason,
    )

    log_action(
        user_id=performed_by_user_id,
        action="ADD_STOCK",
        table_name="warehouse_stock",
        record_id=str(record.id),
        details={
            "article_id": article_id,
            "warehouse_id": warehouse_id,
            "quantity_added": str(qty),
            "movement_type": movement_type,
            "reason": reason,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "reference_number": reference_number,
            "warehouse_location_id": warehouse_location_id,
            "ledger_entry_id": str(ledger_entry.id),
            "new_quantity_on_hand": str(record.quantity_on_hand),
            "last_unit_cost": str(record.last_unit_cost or 0),
            "avg_unit_cost": str(record.avg_unit_cost or 0),
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return record


def subtract_stock(
    *,
    article_id: int,
    warehouse_id: int,
    quantity: Decimal | int | float | str,
    performed_by_user_id: int | None,
    movement_type: str = "AJUSTE_MANUAL",
    reason: str = "Salida manual",
    reference_type: str | None = None,
    reference_id: int | None = None,
    reference_number: str | None = None,
    warehouse_location_id: int | None = None,
    commit: bool = True,
) -> WarehouseStock:
    qty = _to_decimal(quantity)
    _validate_positive(qty, "La cantidad a rebajar debe ser mayor a 0.")

    record = get_warehouse_stock_record(article_id, warehouse_id)
    if not record:
        raise InventoryServiceError("No existe stock registrado para ese artículo en esa bodega.")

    available = Decimal(str(record.available_quantity))
    if qty > available:
        raise InventoryServiceError("No hay suficiente inventario disponible.")

    record.quantity_on_hand = Decimal(str(record.quantity_on_hand or 0)) - qty

    if warehouse_location_id:
        location_record = get_location_stock_record(article_id, warehouse_location_id)
        if not location_record:
            raise InventoryServiceError("No existe stock por ubicación para ese artículo en esa ubicación.")
        if Decimal(str(location_record.quantity or 0)) < qty:
            raise InventoryServiceError("No hay suficiente inventario en la ubicación indicada.")
        location_record.quantity_on_hand = Decimal(str(location_record.quantity or 0)) - qty

    ledger_entry = create_inventory_ledger_entry(
        movement_type=movement_type,
        warehouse_id=warehouse_id,
        article_id=article_id,
        quantity_change=(qty * Decimal("-1")),
        performed_by_user_id=performed_by_user_id,
        warehouse_location_id=warehouse_location_id,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_number=reference_number,
        notes=reason,
    )

    log_action(
        user_id=performed_by_user_id,
        action="SUBTRACT_STOCK",
        table_name="warehouse_stock",
        record_id=str(record.id),
        details={
            "article_id": article_id,
            "warehouse_id": warehouse_id,
            "quantity_subtracted": str(qty),
            "movement_type": movement_type,
            "reason": reason,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "reference_number": reference_number,
            "warehouse_location_id": warehouse_location_id,
            "ledger_entry_id": str(ledger_entry.id),
            "new_quantity_on_hand": str(record.quantity_on_hand),
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return record


def reserve_stock(
    *,
    article_id: int,
    warehouse_id: int,
    quantity: Decimal | int | float | str,
    performed_by_user_id: int | None,
    reason: str = "RESERVA",
    commit: bool = True,
) -> WarehouseStock:
    qty = _to_decimal(quantity)
    _validate_positive(qty, "La cantidad a reservar debe ser mayor a 0.")

    record = get_warehouse_stock_record(article_id, warehouse_id)
    if not record:
        raise InventoryServiceError("No existe stock registrado para ese artículo en esa bodega.")

    available = Decimal(str(record.available_quantity))
    if qty > available:
        raise InventoryServiceError("No hay suficiente inventario disponible para reservar.")

    record.reserved_quantity = Decimal(str(record.reserved_quantity or 0)) + qty

    log_action(
        user_id=performed_by_user_id,
        action="RESERVE_STOCK",
        table_name="warehouse_stock",
        record_id=str(record.id),
        details={
            "article_id": article_id,
            "warehouse_id": warehouse_id,
            "quantity_reserved": str(qty),
            "reason": reason,
            "new_reserved_quantity": str(record.reserved_quantity),
            "available_quantity": str(record.available_quantity),
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return record


def release_reserved_stock(
    *,
    article_id: int,
    warehouse_id: int,
    quantity: Decimal | int | float | str,
    performed_by_user_id: int | None,
    reason: str = "LIBERAR_RESERVA",
    commit: bool = True,
) -> WarehouseStock:
    qty = _to_decimal(quantity)
    _validate_positive(qty, "La cantidad a liberar debe ser mayor a 0.")

    record = get_warehouse_stock_record(article_id, warehouse_id)
    if not record:
        raise InventoryServiceError("No existe stock registrado para ese artículo en esa bodega.")

    reserved = Decimal(str(record.reserved_quantity or 0))
    if qty > reserved:
        raise InventoryServiceError("No se puede liberar más reserva de la existente.")

    record.reserved_quantity = reserved - qty

    log_action(
        user_id=performed_by_user_id,
        action="RELEASE_RESERVED_STOCK",
        table_name="warehouse_stock",
        record_id=str(record.id),
        details={
            "article_id": article_id,
            "warehouse_id": warehouse_id,
            "quantity_released": str(qty),
            "reason": reason,
            "new_reserved_quantity": str(record.reserved_quantity),
            "available_quantity": str(record.available_quantity),
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return record


def transfer_stock(
    *,
    article_id: int,
    origin_warehouse_id: int,
    destination_warehouse_id: int,
    quantity: Decimal | int | float | str,
    performed_by_user_id: int | None,
    reason: str = "Traslado entre bodegas",
    reference_type: str = "TRANSFER",
    reference_id: int | None = None,
    reference_number: str | None = None,
    commit: bool = True,
) -> tuple[WarehouseStock, WarehouseStock]:
    qty = _to_decimal(quantity)
    _validate_positive(qty, "La cantidad a trasladar debe ser mayor a 0.")

    if origin_warehouse_id == destination_warehouse_id:
        raise InventoryServiceError("La bodega origen y destino no pueden ser la misma.")

    origin_record = get_warehouse_stock_record(article_id, origin_warehouse_id)
    if not origin_record:
        raise InventoryServiceError("No existe stock en la bodega origen.")

    available = Decimal(str(origin_record.available_quantity))
    if qty > available:
        raise InventoryServiceError("No hay suficiente inventario disponible en la bodega origen.")

    destination_record = get_or_create_warehouse_stock_record(article_id, destination_warehouse_id)

    origin_record.quantity_on_hand = Decimal(str(origin_record.quantity_on_hand or 0)) - qty
    destination_record.quantity_on_hand = Decimal(str(destination_record.quantity_on_hand or 0)) + qty

    salida_entry = create_inventory_ledger_entry(
        movement_type="TRASLADO_SALIDA",
        warehouse_id=origin_warehouse_id,
        related_warehouse_id=destination_warehouse_id,
        article_id=article_id,
        quantity_change=(qty * Decimal("-1")),
        performed_by_user_id=performed_by_user_id,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_number=reference_number,
        notes=reason,
    )

    entrada_entry = create_inventory_ledger_entry(
        movement_type="TRASLADO_ENTRADA",
        warehouse_id=destination_warehouse_id,
        related_warehouse_id=origin_warehouse_id,
        article_id=article_id,
        quantity_change=qty,
        performed_by_user_id=performed_by_user_id,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_number=reference_number,
        notes=reason,
    )

    log_action(
        user_id=performed_by_user_id,
        action="TRANSFER_STOCK",
        table_name="warehouse_stock",
        record_id=f"{origin_record.id}->{destination_record.id}",
        details={
            "article_id": article_id,
            "origin_warehouse_id": origin_warehouse_id,
            "destination_warehouse_id": destination_warehouse_id,
            "quantity_transferred": str(qty),
            "reason": reason,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "reference_number": reference_number,
            "salida_ledger_entry_id": str(salida_entry.id),
            "entrada_ledger_entry_id": str(entrada_entry.id),
            "origin_new_quantity_on_hand": str(origin_record.quantity_on_hand),
            "destination_new_quantity_on_hand": str(destination_record.quantity_on_hand),
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return origin_record, destination_record


def get_article_stock_summary(article_id: int) -> list[dict]:
    article = Article.query.get(article_id)
    if not article:
        raise InventoryServiceError("El artículo no existe.")

    rows = (
        db.session.query(WarehouseStock, Warehouse)
        .join(Warehouse, Warehouse.id == WarehouseStock.warehouse_id)
        .filter(WarehouseStock.article_id == article_id)
        .order_by(Warehouse.site_id.asc(), Warehouse.name.asc())
        .all()
    )

    summary = []
    for stock, warehouse in rows:
        summary.append(
            {
                "warehouse_id": warehouse.id,
                "warehouse_name": warehouse.name,
                "warehouse_code": warehouse.code,
                "warehouse_type": warehouse.warehouse_type,
                "site_id": warehouse.site_id,
                "quantity_on_hand": str(stock.quantity_on_hand),
                "reserved_quantity": str(stock.reserved_quantity),
                "available_quantity": str(stock.available_quantity),
            }
        )

    return summary


def get_inventory_by_warehouse(warehouse_id: int) -> list[dict]:
    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        raise InventoryServiceError("La bodega no existe.")

    rows = (
        db.session.query(WarehouseStock, Article)
        .join(Article, Article.id == WarehouseStock.article_id)
        .filter(WarehouseStock.warehouse_id == warehouse_id)
        .order_by(Article.name.asc())
        .all()
    )

    result = []
    for stock, article in rows:
        result.append(
            {
                "article_id": article.id,
                "code": article.code,
                "name": article.name,
                "quantity_on_hand": str(stock.quantity_on_hand),
                "last_unit_cost": str(stock.last_unit_cost or 0),
                "avg_unit_cost": str(stock.avg_unit_cost or 0),
            }
        )

    return result


def get_structures_by_site_and_type(site_id: int, warehouse_type: str) -> list[Warehouse]:
    return (
        Warehouse.query
        .filter(
            Warehouse.site_id == site_id,
            Warehouse.warehouse_type == warehouse_type
        )
        .order_by(Warehouse.name.asc())
        .all()
    )


def get_inventory_with_warehouse_info(warehouse_id: int) -> dict:
    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        raise InventoryServiceError("La bodega no existe.")

    items = get_inventory_by_warehouse(warehouse_id)

    return {
        "warehouse": {
            "id": warehouse.id,
            "name": warehouse.name,
            "code": warehouse.code,
            "type": warehouse.warehouse_type,
            "site_id": warehouse.site_id,
        },
        "items": items,
    }