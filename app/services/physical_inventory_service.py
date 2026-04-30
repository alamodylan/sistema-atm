from datetime import datetime, UTC
from decimal import Decimal

from app.extensions import db
from app.models.physical_inventory import PhysicalInventory
from app.models.physical_inventory_line import PhysicalInventoryLine
from app.models.inventory import WarehouseStock
from app.models.inventory import InventoryLedger


def create_physical_inventory(warehouse_id, site_id, user_id):
    # 🔢 consecutivo simple
    last = PhysicalInventory.query.order_by(PhysicalInventory.id.desc()).first()
    number = f"INV-FIS-{(last.id + 1) if last else 1:06d}"

    inventory = PhysicalInventory(
        number=number,
        warehouse_id=warehouse_id,
        site_id=site_id,
        created_by_user_id=user_id,
        status="BORRADOR",
        created_at=datetime.now(UTC),
    )

    db.session.add(inventory)
    db.session.flush()  # para tener ID

    # 🔥 AQUÍ SE TOMA EL SNAPSHOT
    stock_items = WarehouseStock.query.filter_by(
        warehouse_id=warehouse_id
    ).all()

    for stock in stock_items:
        line = PhysicalInventoryLine(
            physical_inventory_id=inventory.id,
            article_id=stock.article_id,
            system_quantity=stock.quantity_on_hand or Decimal("0"),
        )
        db.session.add(line)

    db.session.commit()

    return inventory



def apply_physical_inventory_adjustment(inventory_id, user_id):
    inventory = PhysicalInventory.query.get_or_404(inventory_id)

    # 🔒 VALIDACIONES CRÍTICAS
    if inventory.status == "AJUSTADO":
        raise Exception("Este inventario ya fue ajustado.")

    if inventory.status not in ["FINALIZADO"]:
        raise Exception("El inventario debe estar FINALIZADO para aplicar ajustes.")

    lines = PhysicalInventoryLine.query.filter_by(
        physical_inventory_id=inventory.id
    ).all()

    # Validar que TODAS las líneas tengan conteo
    for line in lines:
        if line.physical_quantity is None:
            raise Exception("Existen líneas sin conteo físico.")

    try:
        for line in lines:
            system_qty = line.system_quantity or Decimal("0")
            physical_qty = line.physical_quantity or Decimal("0")

            difference = physical_qty - system_qty

            if difference == 0:
                continue

            # 🔍 Buscar stock actual
            stock = WarehouseStock.query.filter_by(
                warehouse_id=inventory.warehouse_id,
                article_id=line.article_id
            ).first()

            if not stock:
                raise Exception(f"No se encontró stock para artículo {line.article_id}")

            # 💰 costo (usar promedio si existe)
            unit_cost = stock.avg_unit_cost or stock.last_unit_cost or Decimal("0")

            # 🔥 ACTUALIZAR STOCK
            stock.quantity_on_hand = (stock.quantity_on_hand or Decimal("0")) + difference

            # 🧾 CREAR MOVIMIENTO EN KARDEX
            ledger = InventoryLedger(
                movement_type="AJUSTE_INVENTARIO_FISICO",
                warehouse_id=inventory.warehouse_id,
                article_id=line.article_id,
                quantity_change=difference,
                unit_cost=unit_cost,
                total_cost=unit_cost * difference,
                reference_type="PHYSICAL_INVENTORY",
                reference_id=inventory.id,
                reference_number=inventory.number,
                performed_by_user_id=user_id,
                notes=f"Ajuste por inventario físico {inventory.number}",
                created_at=datetime.now(UTC),
            )

            db.session.add(ledger)

        # 🔥 ACTUALIZAR INVENTARIO
        inventory.status = "AJUSTADO"
        inventory.adjusted_at = datetime.now(UTC)

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        raise e

    return True