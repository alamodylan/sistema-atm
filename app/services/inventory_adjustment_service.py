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


def _to_decimal(value, field_name="cantidad", allow_decimals=False):
    """
    Convierte un valor a Decimal sin redondearlo.

    - No permite valores vacíos.
    - No permite valores negativos.
    - Cuando allow_decimals=False, exige una cantidad entera.
    - Cuando allow_decimals=True, conserva exactamente la precisión recibida.
    """
    if value is None or str(value).strip() == "":
        raise InventoryAdjustmentServiceError(
            f"Debe ingresar la {field_name}."
        )

    raw_value = str(value).strip()

    # Permite que accidentalmente llegue una coma decimal.
    # Ejemplo: "10,5" se interpreta como "10.5".
    if "," in raw_value and "." not in raw_value:
        raw_value = raw_value.replace(",", ".")

    try:
        decimal_value = Decimal(raw_value)
    except (InvalidOperation, TypeError, ValueError):
        raise InventoryAdjustmentServiceError(
            f"La {field_name} no es válida."
        )

    if not decimal_value.is_finite():
        raise InventoryAdjustmentServiceError(
            f"La {field_name} no es válida."
        )

    if decimal_value < 0:
        raise InventoryAdjustmentServiceError(
            f"La {field_name} no puede ser negativa."
        )

    if (
        not allow_decimals
        and decimal_value != decimal_value.to_integral_value()
    ):
        raise InventoryAdjustmentServiceError(
            f"La {field_name} debe ser un número entero."
        )

    # No usar quantize: devuelve exactamente el Decimal recibido.
    return decimal_value


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
    Busca un artículo por código o código de barras y devuelve
    la existencia actual exacta en la bodega seleccionada.
    """
    if not warehouse_id:
        raise InventoryAdjustmentServiceError(
            "Debe seleccionar una bodega."
        )

    if not code_or_barcode:
        raise InventoryAdjustmentServiceError(
            "Debe ingresar un código o código de barras."
        )

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
        raise InventoryAdjustmentServiceError(
            "No se encontró ningún artículo con ese código."
        )

    stock = (
        WarehouseStock.query
        .filter(
            WarehouseStock.warehouse_id == warehouse_id,
            WarehouseStock.article_id == article.id,
        )
        .first()
    )

    # Conservar la cantidad exacta almacenada.
    current_quantity = Decimal("0")

    if stock and stock.quantity_on_hand is not None:
        current_quantity = Decimal(
            str(stock.quantity_on_hand)
        )

    unit_code = None

    if article.unit_id:
        unit = db.session.execute(
            db.text(
                """
                SELECT code
                FROM atm.units
                WHERE id = :id
                """
            ),
            {"id": article.unit_id},
        ).first()

        if unit:
            unit_code = str(unit.code or "").strip().upper()

    return {
        "article_id": article.id,
        "code": article.code,
        "barcode": article.barcode,
        "name": article.name,
        "current_quantity": current_quantity,
        "unit_code": unit_code,
    }


def create_inventory_adjustment(
    *,
    site_id,
    warehouse_id,
    created_by_user_id,
    lines,
    notes=None,
):
    if not site_id:
        raise InventoryAdjustmentServiceError(
            "No se recibió el predio del ajuste."
        )

    if not warehouse_id:
        raise InventoryAdjustmentServiceError(
            "Debe seleccionar una bodega."
        )

    if not created_by_user_id:
        raise InventoryAdjustmentServiceError(
            "No se recibió el usuario que realiza el ajuste."
        )

    if not lines:
        raise InventoryAdjustmentServiceError(
            "Debe agregar al menos una línea al ajuste."
        )

    warehouse = Warehouse.query.get(warehouse_id)

    if not warehouse:
        raise InventoryAdjustmentServiceError(
            "La bodega seleccionada no existe."
        )

    if warehouse.site_id != site_id:
        raise InventoryAdjustmentServiceError(
            "La bodega seleccionada no pertenece al predio activo."
        )

    seen_articles = set()
    clean_lines = []

    decimal_unit_codes = {
        "METRO",
        "LITRO",
        "GALON",
        "KG",
    }

    for raw_line in lines:
        article_id = raw_line.get("article_id")
        quantity_after = raw_line.get("quantity_after")

        if not article_id:
            raise InventoryAdjustmentServiceError(
                "Hay una línea sin artículo."
            )

        try:
            article_id = int(article_id)
        except (TypeError, ValueError):
            raise InventoryAdjustmentServiceError(
                "Hay una línea con un artículo inválido."
            )

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

        unit_code = None

        if article.unit_id:
            unit_row = db.session.execute(
                db.text(
                    """
                    SELECT code
                    FROM atm.units
                    WHERE id = :unit_id
                    """
                ),
                {"unit_id": article.unit_id},
            ).first()

            if unit_row:
                unit_code = str(
                    unit_row.code or ""
                ).strip().upper()

        allow_decimals = unit_code in decimal_unit_codes

        quantity_after_decimal = _to_decimal(
            quantity_after,
            "cantidad nueva",
            allow_decimals=allow_decimals,
        )

        clean_lines.append(
            {
                "article": article,
                "unit_code": unit_code,
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

        applied_count = 0
        skipped_count = 0
        skipped_lines = []

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
                    quantity_on_hand=Decimal("0"),
                    reserved_quantity=Decimal("0"),
                    last_unit_cost=Decimal("0"),
                    avg_unit_cost=Decimal("0"),
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )

                db.session.add(stock)
                db.session.flush()

            quantity_before = Decimal(
                str(stock.quantity_on_hand or 0)
            )

            # No aplicar quantize ni round.
            difference = quantity_after - quantity_before

            adjustment_line = InventoryAdjustmentLine(
                adjustment_id=adjustment.id,
                article_id=article.id,
                quantity_before=quantity_before,
                quantity_after=quantity_after,
                difference=difference,
                created_at=datetime.now(UTC),
            )

            db.session.add(adjustment_line)

            # Guardar exactamente el valor digitado.
            stock.quantity_on_hand = quantity_after

            if hasattr(stock, "updated_at"):
                stock.updated_at = datetime.now(UTC)

            if difference == Decimal("0"):
                skipped_count += 1

                skipped_lines.append(
                    f"{article.code}: sin diferencia. "
                    f"Cantidad anterior {quantity_before}, "
                    f"cantidad nueva {quantity_after}."
                )

                continue

            ledger = InventoryLedger(
                movement_type="AJUSTE_MANUAL",
                warehouse_id=warehouse_id,
                related_warehouse_id=None,
                warehouse_location_id=None,
                article_id=article.id,
                quantity_change=difference,
                unit_cost=getattr(
                    stock,
                    "last_unit_cost",
                    None,
                ),
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
            applied_count += 1

        db.session.commit()

        adjustment.applied_count = applied_count
        adjustment.skipped_count = skipped_count
        adjustment.skipped_lines = skipped_lines

        return adjustment

    except IntegrityError as exc:
        db.session.rollback()

        raise InventoryAdjustmentServiceError(
            "No se pudo guardar el ajuste por un conflicto "
            "de integridad en la base de datos."
        ) from exc

    except InventoryAdjustmentServiceError:
        db.session.rollback()
        raise

    except Exception as exc:
        db.session.rollback()

        raise InventoryAdjustmentServiceError(
            f"No se pudo guardar el ajuste de inventario: {exc}"
        ) from exc


def get_adjustment_by_id(adjustment_id):
    adjustment = InventoryAdjustment.query.get(adjustment_id)

    if not adjustment:
        raise InventoryAdjustmentServiceError("El ajuste solicitado no existe.")

    return adjustment


def list_adjustments(
    site_id=None,
    warehouse_id=None,
    search=None,
    page=1,
    per_page=100,
):
    query = InventoryAdjustment.query

    if site_id:
        query = query.filter(
            InventoryAdjustment.site_id == site_id
        )

    if warehouse_id:
        query = query.filter(
            InventoryAdjustment.warehouse_id == warehouse_id
        )

    if search:
        search = str(search).strip()

        if search:
            query = query.filter(
                InventoryAdjustment.notes.ilike(f"%{search}%")
            )

    return (
        query
        .order_by(
            InventoryAdjustment.created_at.desc(),
            InventoryAdjustment.id.desc(),
        )
        .paginate(
            page=page,
            per_page=per_page,
            error_out=False,
        )
    )