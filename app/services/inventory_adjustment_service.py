from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.article import Article
from app.models.inventory_adjustment import InventoryAdjustment
from app.models.inventory_adjustment_line import InventoryAdjustmentLine
from app.models.inventory import InventoryLedger
from app.models.warehouse import Warehouse
from app.models.inventory import WarehouseStock


class InventoryAdjustmentServiceError(Exception):
    pass


def _to_decimal(value, field_name="cantidad"):
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise InventoryAdjustmentServiceError(f"La {field_name} no es válida.")

    if decimal_value < 0:
        raise InventoryAdjustmentServiceError(f"La {field_name} no puede ser negativa.")

    if decimal_value != decimal_value.to_integral_value():
        raise InventoryAdjustmentServiceError(f"La {field_name} debe ser un número entero.")

    return decimal_value.quantize(Decimal("0.00"))


def _generate_adjustment_number():
    """
    Genera consecutivo corto:
    AJ-0000001
    AJ-0000002
    """
    last_id = db.session.query(func.max(InventoryAdjustment.id)).scalar() or 0
    next_number = int(last_id) + 1
    return f"AJ-{next_number:07d}"


def get_adjustable_warehouses_for_site(site_id):
    """
    Bodegas activas del predio actual.
    """
    return (
        Warehouse.query
        .filter(
            Warehouse.site_id == site_id,
            Warehouse.is_active.is_(True),
        )
        .order_by(Warehouse.name.asc())
        .all()
    )


def find_article_for_adjustment(warehouse_id, code_or_barcode):
    """
    Busca artículo por código o barcode y devuelve stock actual en esa bodega.
    Sirve para scanner o digitación manual.
    """
    if not code_or_barcode:
        raise InventoryAdjustmentServiceError("Debe ingresar un código o código de barras.")

    cleaned = str(code_or_barcode).strip()

    article = (
        Article.query
        .filter(
            db.or_(
                Article.code == cleaned,
                Article.barcode == cleaned,
            )
        )
        .first()
    )

    if not article:
        raise InventoryAdjustmentServiceError("No se encontró ningún artículo con ese código.")

    stock = (
        WarehouseStock.query
        .filter(
            WarehouseStock.warehouse_id == warehouse_id,
            WarehouseStock.article_id == article.id,
        )
        .first()
    )

    current_quantity = Decimal("0.00")
    if stock:
        current_quantity = Decimal(str(stock.quantity_on_hand or 0)).quantize(Decimal("0.00"))

    return {
        "article_id": article.id,
        "code": article.code,
        "barcode": article.barcode,
        "name": article.name,
        "current_quantity": current_quantity,
    }


def create_inventory_adjustment(
    *,
    site_id,
    warehouse_id,
    created_by_user_id,
    lines,
    notes=None,
):
    """
    Crea un ajuste manual de inventario.

    lines esperado:
    [
        {
            "article_id": 1,
            "quantity_after": 10
        },
        ...
    ]

    Este método:
    1. Crea encabezado inventory_adjustments.
    2. Crea líneas inventory_adjustment_lines.
    3. Actualiza warehouse_stock.
    4. Registra inventory_ledger con quantity_change positivo o negativo.
    """

    if not site_id:
        raise InventoryAdjustmentServiceError("No se recibió el predio del ajuste.")

    if not warehouse_id:
        raise InventoryAdjustmentServiceError("Debe seleccionar una bodega.")

    if not created_by_user_id:
        raise InventoryAdjustmentServiceError("No se recibió el usuario que realiza el ajuste.")

    if not lines:
        raise InventoryAdjustmentServiceError("Debe agregar al menos una línea al ajuste.")

    warehouse = Warehouse.query.get(warehouse_id)

    if not warehouse:
        raise InventoryAdjustmentServiceError("La bodega seleccionada no existe.")

    if warehouse.site_id != site_id:
        raise InventoryAdjustmentServiceError(
            "La bodega seleccionada no pertenece al predio activo."
        )

    seen_articles = set()
    clean_lines = []

    for raw_line in lines:
        article_id = raw_line.get("article_id")
        quantity_after = raw_line.get("quantity_after")

        if not article_id:
            raise InventoryAdjustmentServiceError("Hay una línea sin artículo.")

        if article_id in seen_articles:
            raise InventoryAdjustmentServiceError(
                "No se permite repetir el mismo artículo en un ajuste."
            )

        seen_articles.add(article_id)

        article = Article.query.get(article_id)

        if not article:
            raise InventoryAdjustmentServiceError(
                f"El artículo con ID {article_id} no existe."
            )

        quantity_after_decimal = _to_decimal(quantity_after, "cantidad nueva")

        clean_lines.append(
            {
                "article": article,
                "quantity_after": quantity_after_decimal,
            }
        )

    try:
        adjustment = InventoryAdjustment(
            number=_generate_adjustment_number(),
            site_id=site_id,
            warehouse_id=warehouse_id,
            created_by_user_id=created_by_user_id,
            notes=notes,
            created_at=datetime.now(UTC),
        )

        db.session.add(adjustment)
        db.session.flush()

        for item in clean_lines:
            article = item["article"]
            quantity_after = item["quantity_after"]

            stock = (
                WarehouseStock.query
                .filter(
                    WarehouseStock.warehouse_id == warehouse_id,
                    WarehouseStock.article_id == article.id,
                )
                .with_for_update()
                .first()
            )

            if not stock:
                stock = WarehouseStock(
                    warehouse_id=warehouse_id,
                    article_id=article.id,
                    quantity_on_hand=Decimal("0.00"),
                    reserved_quantity=Decimal("0.00"),
                )
                db.session.add(stock)
                db.session.flush()

            quantity_before = Decimal(str(stock.quantity_on_hand or 0)).quantize(
                Decimal("0.00")
            )

            difference = (quantity_after - quantity_before).quantize(Decimal("0.00"))

            adjustment_line = InventoryAdjustmentLine(
                adjustment_id=adjustment.id,
                article_id=article.id,
                quantity_before=quantity_before,
                quantity_after=quantity_after,
                difference=difference,
                created_at=datetime.now(UTC),
            )

            db.session.add(adjustment_line)

            stock.quantity_on_hand = quantity_after

            ledger = InventoryLedger(
                movement_type="ADJUSTMENT",
                warehouse_id=warehouse_id,
                related_warehouse_id=None,
                warehouse_location_id=None,
                article_id=article.id,
                quantity_change=difference,
                unit_cost=getattr(stock, "last_unit_cost", None),
                total_cost=None,
                reference_type="INVENTORY_ADJUSTMENT",
                reference_id=adjustment.id,
                reference_number=adjustment.number,
                notes=(
                    f"Ajuste manual de inventario. "
                    f"Cantidad anterior: {quantity_before}, "
                    f"cantidad nueva: {quantity_after}, "
                    f"diferencia: {difference}."
                ),
                performed_by_user_id=created_by_user_id,
                created_at=datetime.now(UTC),
            )

            db.session.add(ledger)

        db.session.commit()
        return adjustment

    except IntegrityError as exc:
        db.session.rollback()
        raise InventoryAdjustmentServiceError(
            "No se pudo guardar el ajuste por un conflicto de integridad en la base de datos."
        ) from exc

    except Exception:
        db.session.rollback()
        raise


def get_adjustment_by_id(adjustment_id):
    adjustment = InventoryAdjustment.query.get(adjustment_id)

    if not adjustment:
        raise InventoryAdjustmentServiceError("El ajuste solicitado no existe.")

    return adjustment


def list_adjustments(site_id=None, warehouse_id=None, limit=100):
    query = InventoryAdjustment.query

    if site_id:
        query = query.filter(InventoryAdjustment.site_id == site_id)

    if warehouse_id:
        query = query.filter(InventoryAdjustment.warehouse_id == warehouse_id)

    return (
        query
        .order_by(InventoryAdjustment.created_at.desc())
        .limit(limit)
        .all()
    )