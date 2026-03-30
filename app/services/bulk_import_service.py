from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models.article import Article
from app.models.equipment import Equipment
from app.models.inventory import InventoryLedger, WarehouseLocationStock, WarehouseStock
from app.models.item_category import ItemCategory
from app.models.mechanic import Mechanic
from app.models.site import Site
from app.models.unit import Unit
from app.models.warehouse import Warehouse
from app.models.warehouse_location import WarehouseLocation

# Si ya tienes supplier.py, esto funcionará de una vez.
# Si aún no existe el modelo, la carga de proveedores fallará con un mensaje claro.
try:
    from app.models.supplier import Supplier
except Exception:  # pragma: no cover
    Supplier = None


class BulkImportError(Exception):
    pass


def _parse_bool(value) -> bool:
    if value is None:
        return True

    value = str(value).strip().lower()

    if value == "":
        return True

    return value in ("1", "true", "si", "sí", "yes", "y", "x")


def _parse_decimal(value, field_name: str = "cantidad") -> Decimal:
    if value is None or str(value).strip() == "":
        raise BulkImportError(f"El campo {field_name} es obligatorio.")

    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise BulkImportError(f"El campo {field_name} no tiene un valor válido.") from exc


def _clean(value) -> str:
    return str(value or "").strip()


def _set_quantity_on_hand(record, quantity: Decimal) -> None:
    """
    Soporta tanto modelos correctos con quantity_on_hand como versiones
    antiguas que todavía usen 'quantity' como alias interno.
    """
    if hasattr(record, "quantity_on_hand"):
        record.quantity_on_hand = quantity
    elif hasattr(record, "quantity"):
        record.quantity = quantity
    else:
        raise BulkImportError("El modelo de stock no tiene un campo de cantidad reconocido.")


def _get_quantity_on_hand(record) -> Decimal:
    if hasattr(record, "quantity_on_hand"):
        return Decimal(str(record.quantity_on_hand or 0))
    if hasattr(record, "quantity"):
        return Decimal(str(record.quantity or 0))
    raise BulkImportError("El modelo de stock no tiene un campo de cantidad reconocido.")


def _get_reserved_quantity(record) -> Decimal:
    if hasattr(record, "reserved_quantity"):
        return Decimal(str(record.reserved_quantity or 0))
    return Decimal("0")


def _create_ledger_entry(
    *,
    movement_type: str,
    warehouse_id: int,
    article_id: int,
    quantity_change: Decimal,
    performed_by_user_id: int | None,
    notes: str,
    related_warehouse_id: int | None = None,
    warehouse_location_id: int | None = None,
) -> None:
    entry = InventoryLedger(
        movement_type=movement_type,
        warehouse_id=warehouse_id,
        related_warehouse_id=related_warehouse_id,
        warehouse_location_id=warehouse_location_id,
        article_id=article_id,
        quantity_change=quantity_change,
        unit_cost=None,
        total_cost=None,
        reference_type="CARGA_MASIVA",
        reference_id=None,
        reference_number=None,
        notes=notes,
        performed_by_user_id=performed_by_user_id,
    )
    db.session.add(entry)


def _ensure_active_site(site_id: int) -> Site:
    site = Site.query.get(site_id)
    if not site:
        raise BulkImportError("El predio activo no existe.")
    return site


# =========================================================
# MECÁNICOS (POR PREDIO)
# =========================================================
def import_mechanics(rows: list[dict], *, site_id: int) -> dict:
    _ensure_active_site(site_id)

    created = 0
    updated = 0
    skipped = 0

    for row in rows:
        try:
            code = _clean(row.get("codigo"))
            name = _clean(row.get("nombre"))
            active_raw = row.get("activo")

            if not code or not name:
                skipped += 1
                continue

            is_active = _parse_bool(active_raw)

            mechanic = Mechanic.query.filter_by(
                code=code,
                site_id=site_id,
            ).first()

            if mechanic:
                mechanic.name = name
                mechanic.is_active = is_active
                updated += 1
            else:
                db.session.add(
                    Mechanic(
                        site_id=site_id,
                        code=code,
                        name=name,
                        is_active=is_active,
                    )
                )
                created += 1

        except Exception:
            skipped += 1
            continue

    db.session.commit()

    return {"created": created, "updated": updated, "skipped": skipped}


# =========================================================
# UNIDADES (GLOBAL)
# =========================================================
def import_units(rows: list[dict]) -> dict:
    created = 0
    updated = 0
    skipped = 0

    for row in rows:
        try:
            code = _clean(row.get("codigo"))
            name = _clean(row.get("nombre"))

            if not code or not name:
                skipped += 1
                continue

            unit = Unit.query.filter_by(code=code).first()

            if unit:
                unit.name = name
                updated += 1
            else:
                db.session.add(Unit(code=code, name=name))
                created += 1

        except Exception:
            skipped += 1
            continue

    db.session.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


# =========================================================
# CATEGORÍAS (GLOBAL)
# =========================================================
def import_categories(rows: list[dict]) -> dict:
    created = 0
    updated = 0
    skipped = 0

    for row in rows:
        try:
            code = _clean(row.get("codigo"))
            name = _clean(row.get("nombre"))
            description = _clean(row.get("descripcion")) or None

            if not code or not name:
                skipped += 1
                continue

            category = ItemCategory.query.filter_by(code=code).first()

            if category:
                category.name = name
                category.description = description
                updated += 1
            else:
                db.session.add(
                    ItemCategory(
                        code=code,
                        name=name,
                        description=description,
                    )
                )
                created += 1

        except Exception:
            skipped += 1
            continue

    db.session.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


# =========================================================
# BODEGAS (POR PREDIO)
# =========================================================
def import_warehouses(rows: list[dict], *, site_id: int) -> dict:
    _ensure_active_site(site_id)

    created = 0
    updated = 0
    skipped = 0

    valid_types = {"BODEGA", "MINIBODEGA", "CAJA_HERRAMIENTAS"}

    for row in rows:
        try:
            code = _clean(row.get("codigo"))
            name = _clean(row.get("nombre"))
            warehouse_type = _clean(row.get("tipo_bodega")).upper()
            active_raw = row.get("activo")

            if not code or not name or not warehouse_type:
                skipped += 1
                continue

            if warehouse_type not in valid_types:
                skipped += 1
                continue

            is_active = _parse_bool(active_raw)

            warehouse = Warehouse.query.filter_by(code=code).first()

            if warehouse:
                warehouse.site_id = site_id
                warehouse.name = name
                warehouse.warehouse_type = warehouse_type
                warehouse.is_active = is_active
                updated += 1
            else:
                db.session.add(
                    Warehouse(
                        site_id=site_id,
                        code=code,
                        name=name,
                        warehouse_type=warehouse_type,
                        is_active=is_active,
                    )
                )
                created += 1

        except Exception:
            skipped += 1
            continue

    db.session.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


# =========================================================
# UBICACIONES (POR PREDIO)
# =========================================================
def import_locations(rows: list[dict], *, site_id: int) -> dict:
    _ensure_active_site(site_id)

    created = 0
    updated = 0
    skipped = 0

    for row in rows:
        try:
            warehouse_code = _clean(row.get("codigo_bodega"))
            code = _clean(row.get("codigo"))
            aisle = _clean(row.get("pasillo")) or None
            shelf = _clean(row.get("estante")) or None
            level_no = _clean(row.get("nivel")) or None
            position_no = _clean(row.get("posicion")) or None
            description = _clean(row.get("descripcion")) or None
            active_raw = row.get("activo")

            if not warehouse_code or not code:
                skipped += 1
                continue

            warehouse = Warehouse.query.filter_by(
                code=warehouse_code,
                site_id=site_id,
            ).first()

            if not warehouse:
                skipped += 1
                continue

            is_active = _parse_bool(active_raw)

            location = WarehouseLocation.query.filter_by(
                warehouse_id=warehouse.id,
                code=code,
            ).first()

            if location:
                location.aisle = aisle
                location.shelf = shelf
                location.level_no = level_no
                location.position_no = position_no
                location.description = description
                location.is_active = is_active
                updated += 1
            else:
                db.session.add(
                    WarehouseLocation(
                        warehouse_id=warehouse.id,
                        code=code,
                        aisle=aisle,
                        shelf=shelf,
                        level_no=level_no,
                        position_no=position_no,
                        description=description,
                        is_active=is_active,
                    )
                )
                created += 1

        except Exception:
            skipped += 1
            continue

    db.session.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


# =========================================================
# ARTÍCULOS (GLOBAL)
# =========================================================
def import_articles(rows: list[dict]) -> dict:
    created = 0
    updated = 0
    skipped = 0

    for row in rows:
        try:
            code = _clean(row.get("codigo"))
            name = _clean(row.get("nombre"))
            unit_code = _clean(row.get("codigo_unidad"))
            category_code = _clean(row.get("codigo_categoria"))
            description = _clean(row.get("descripcion")) or None
            family_code = _clean(row.get("codigo_familia")) or None
            barcode = _clean(row.get("codigo_barras")) or None
            sap_code = _clean(row.get("codigo_sap")) or None
            is_tool = _parse_bool(row.get("es_herramienta"))
            is_active = _parse_bool(row.get("activo"))

            if not code or not name or not unit_code:
                skipped += 1
                continue

            unit = Unit.query.filter_by(code=unit_code).first()
            if not unit:
                skipped += 1
                continue

            category = None
            if category_code:
                category = ItemCategory.query.filter_by(code=category_code).first()
                if not category:
                    skipped += 1
                    continue

            article = Article.query.filter_by(code=code).first()

            # Validación simple para barcode único
            if barcode:
                barcode_owner = Article.query.filter_by(barcode=barcode).first()
                if barcode_owner and (not article or barcode_owner.id != article.id):
                    skipped += 1
                    continue

            if article:
                article.name = name
                article.description = description
                article.unit_id = unit.id
                article.category_id = category.id if category else None
                article.family_code = family_code
                article.barcode = barcode
                article.sap_code = sap_code
                article.is_tool = is_tool
                article.is_active = is_active
                updated += 1
            else:
                db.session.add(
                    Article(
                        code=code,
                        name=name,
                        description=description,
                        unit_id=unit.id,
                        category_id=category.id if category else None,
                        family_code=family_code,
                        barcode=barcode,
                        sap_code=sap_code,
                        is_tool=is_tool,
                        is_active=is_active,
                    )
                )
                created += 1

        except Exception:
            skipped += 1
            continue

    db.session.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


# =========================================================
# PROVEEDORES (GLOBAL)
# =========================================================
def import_suppliers(rows: list[dict]) -> dict:
    if Supplier is None:
        raise BulkImportError(
            "No existe el modelo Supplier en el proyecto. Cree app/models/supplier.py antes de usar esta carga."
        )

    created = 0
    updated = 0
    skipped = 0

    for row in rows:
        try:
            code = _clean(row.get("codigo")) or None
            commercial_name = _clean(row.get("nombre_comercial"))
            legal_name = _clean(row.get("nombre_legal")) or None
            tax_id = _clean(row.get("cedula_juridica")) or None
            contact_name = _clean(row.get("contacto")) or None
            email = _clean(row.get("correo")) or None
            phone = _clean(row.get("telefono")) or None
            address = _clean(row.get("direccion")) or None
            payment_terms = _clean(row.get("condiciones_pago")) or None
            currency_code = _clean(row.get("moneda")) or None
            is_active = _parse_bool(row.get("activo"))

            if not commercial_name:
                skipped += 1
                continue

            supplier = Supplier.query.filter_by(code=code).first() if code else None

            if supplier:
                supplier.commercial_name = commercial_name
                supplier.legal_name = legal_name
                supplier.tax_id = tax_id
                supplier.contact_name = contact_name
                supplier.email = email
                supplier.phone = phone
                supplier.address = address
                supplier.payment_terms = payment_terms
                supplier.currency_code = currency_code
                supplier.is_active = is_active
                updated += 1
            else:
                db.session.add(
                    Supplier(
                        code=code,
                        commercial_name=commercial_name,
                        legal_name=legal_name,
                        tax_id=tax_id,
                        contact_name=contact_name,
                        email=email,
                        phone=phone,
                        address=address,
                        payment_terms=payment_terms,
                        currency_code=currency_code,
                        is_active=is_active,
                    )
                )
                created += 1

        except Exception:
            skipped += 1
            continue

    db.session.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


# =========================================================
# EQUIPOS (GLOBAL)
# =========================================================
def import_equipment(rows: list[dict]) -> dict:
    created = 0
    updated = 0
    skipped = 0

    valid_types = {"CHASIS", "CABEZAL", "OTRO"}

    for row in rows:
        try:
            code = _clean(row.get("codigo"))
            equipment_type = _clean(row.get("tipo")).upper()
            description = _clean(row.get("descripcion")) or None
            axle_count_raw = _clean(row.get("cantidad_ejes"))
            size_label = _clean(row.get("tamano")) or None
            is_active = _parse_bool(row.get("activo"))

            if not code or not equipment_type:
                skipped += 1
                continue

            if equipment_type not in valid_types:
                skipped += 1
                continue

            axle_count = int(axle_count_raw) if axle_count_raw else None

            equipment = Equipment.query.filter_by(code=code).first()

            if equipment:
                equipment.equipment_type = equipment_type
                equipment.description = description
                equipment.axle_count = axle_count
                equipment.size_label = size_label
                equipment.is_active = is_active
                updated += 1
            else:
                db.session.add(
                    Equipment(
                        code=code,
                        equipment_type=equipment_type,
                        description=description,
                        axle_count=axle_count,
                        size_label=size_label,
                        is_active=is_active,
                    )
                )
                created += 1

        except Exception:
            skipped += 1
            continue

    db.session.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


# =========================================================
# STOCK POR BODEGA (POR PREDIO)
# =========================================================
def import_warehouse_stock(
    rows: list[dict],
    *,
    site_id: int,
    performed_by_user_id: int | None,
) -> dict:
    _ensure_active_site(site_id)

    created = 0
    updated = 0
    skipped = 0

    for row in rows:
        try:
            warehouse_code = _clean(row.get("codigo_bodega"))
            article_code = _clean(row.get("codigo_articulo"))
            final_quantity = _parse_decimal(row.get("cantidad"), "cantidad")

            if not warehouse_code or not article_code:
                skipped += 1
                continue

            warehouse = Warehouse.query.filter_by(
                code=warehouse_code,
                site_id=site_id,
            ).first()
            if not warehouse:
                skipped += 1
                continue

            article = Article.query.filter_by(code=article_code).first()
            if not article:
                skipped += 1
                continue

            stock = WarehouseStock.query.filter_by(
                warehouse_id=warehouse.id,
                article_id=article.id,
            ).first()

            if not stock:
                stock = WarehouseStock(
                    warehouse_id=warehouse.id,
                    article_id=article.id,
                    reserved_quantity=Decimal("0"),
                )
                _set_quantity_on_hand(stock, Decimal("0"))
                db.session.add(stock)
                db.session.flush()
                created += 1

            current_quantity = _get_quantity_on_hand(stock)
            if current_quantity != final_quantity:
                diff = final_quantity - current_quantity
                _set_quantity_on_hand(stock, final_quantity)

                _create_ledger_entry(
                    movement_type="AJUSTE_MANUAL",
                    warehouse_id=warehouse.id,
                    article_id=article.id,
                    quantity_change=diff,
                    performed_by_user_id=performed_by_user_id,
                    notes="Carga masiva de stock por bodega",
                )
                updated += 1

        except Exception:
            skipped += 1
            continue

    db.session.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


# =========================================================
# STOCK POR UBICACIÓN (POR PREDIO)
# =========================================================
def import_location_stock(
    rows: list[dict],
    *,
    site_id: int,
    performed_by_user_id: int | None,
) -> dict:
    _ensure_active_site(site_id)

    created = 0
    updated = 0
    skipped = 0
    touched_pairs: set[tuple[int, int]] = set()

    for row in rows:
        try:
            warehouse_code = _clean(row.get("codigo_bodega"))
            location_code = _clean(row.get("codigo_ubicacion"))
            article_code = _clean(row.get("codigo_articulo"))
            final_quantity = _parse_decimal(row.get("cantidad"), "cantidad")

            if not warehouse_code or not location_code or not article_code:
                skipped += 1
                continue

            warehouse = Warehouse.query.filter_by(
                code=warehouse_code,
                site_id=site_id,
            ).first()
            if not warehouse:
                skipped += 1
                continue

            location = WarehouseLocation.query.filter_by(
                warehouse_id=warehouse.id,
                code=location_code,
            ).first()
            if not location:
                skipped += 1
                continue

            article = Article.query.filter_by(code=article_code).first()
            if not article:
                skipped += 1
                continue

            stock = WarehouseLocationStock.query.filter_by(
                warehouse_location_id=location.id,
                article_id=article.id,
            ).first()

            if not stock:
                stock = WarehouseLocationStock(
                    warehouse_location_id=location.id,
                    article_id=article.id,
                )
                _set_quantity_on_hand(stock, Decimal("0"))
                db.session.add(stock)
                db.session.flush()
                created += 1

            current_quantity = _get_quantity_on_hand(stock)
            if current_quantity != final_quantity:
                diff = final_quantity - current_quantity
                _set_quantity_on_hand(stock, final_quantity)

                _create_ledger_entry(
                    movement_type="AJUSTE_MANUAL",
                    warehouse_id=warehouse.id,
                    warehouse_location_id=location.id,
                    article_id=article.id,
                    quantity_change=diff,
                    performed_by_user_id=performed_by_user_id,
                    notes="Carga masiva de stock por ubicación",
                )
                updated += 1

            touched_pairs.add((warehouse.id, article.id))

        except Exception:
            skipped += 1
            continue

    # Recalcular stock agregado por bodega para las combinaciones tocadas
    for warehouse_id, article_id in touched_pairs:
        total = Decimal("0")
        location_rows = (
            db.session.query(WarehouseLocationStock, WarehouseLocation)
            .join(
                WarehouseLocation,
                WarehouseLocation.id == WarehouseLocationStock.warehouse_location_id,
            )
            .filter(
                WarehouseLocation.warehouse_id == warehouse_id,
                WarehouseLocationStock.article_id == article_id,
            )
            .all()
        )
        for loc_stock, _location in location_rows:
            total += _get_quantity_on_hand(loc_stock)

        agg = WarehouseStock.query.filter_by(
            warehouse_id=warehouse_id,
            article_id=article_id,
        ).first()

        if not agg:
            agg = WarehouseStock(
                warehouse_id=warehouse_id,
                article_id=article_id,
                reserved_quantity=Decimal("0"),
            )
            db.session.add(agg)
            db.session.flush()

        reserved = _get_reserved_quantity(agg)
        if reserved > total:
            reserved = Decimal("0")
            if hasattr(agg, "reserved_quantity"):
                agg.reserved_quantity = reserved

        _set_quantity_on_hand(agg, total)

    db.session.commit()
    return {"created": created, "updated": updated, "skipped": skipped}