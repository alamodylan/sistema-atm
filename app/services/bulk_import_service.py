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
from app.models.item_subcategory import ItemSubcategory
from app.models.article import Article
from app.models.supplier import Supplier
from app.models.article_supplier import ArticleSupplier
from app.models.unit import Unit
from app.extensions import db

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
    subcategories_created = 0
    subcategories_updated = 0
    subcategories_existing = 0

    categories_map = {
        category.code: category
        for category in ItemCategory.query.all()
    }

    subcategories_by_code = {}
    subcategories_by_name = {}

    for subcategory in ItemSubcategory.query.all():
        if subcategory.code:
            subcategories_by_code[
                (
                    subcategory.category_id,
                    subcategory.code.strip().upper(),
                )
            ] = subcategory

        subcategories_by_name[
            (
                subcategory.category_id,
                subcategory.name.strip().lower(),
            )
        ] = subcategory

    for row in rows:
        code = ""
        name = ""

        try:
            code = _clean(row.get("codigo")).upper()
            name = _clean(row.get("nombre"))
            description = _clean(row.get("descripcion")) or None

            subcategory_code = _clean(row.get("codigo_subcategoria")).upper()
            subcategory_name = _clean(row.get("subcategoria"))
            subcategory_description = _clean(row.get("descripcion_subcategoria")) or None

            if not code or not name:
                skipped += 1
                continue

            category = categories_map.get(code)

            if category:
                category.name = name
                category.description = description
                updated += 1
            else:
                category = ItemCategory(
                    code=code,
                    name=name,
                    description=description,
                )

                db.session.add(category)
                db.session.flush()

                categories_map[code] = category
                created += 1

            if subcategory_name:
                subcategory = None

                if subcategory_code:
                    subcategory = subcategories_by_code.get(
                        (
                            category.id,
                            subcategory_code,
                        )
                    )

                if not subcategory:
                    subcategory = subcategories_by_name.get(
                        (
                            category.id,
                            subcategory_name.strip().lower(),
                        )
                    )

                if subcategory:
                    changed = False

                    if subcategory.code != (subcategory_code or subcategory.code):
                        subcategory.code = subcategory_code or subcategory.code
                        changed = True

                    if subcategory.name != subcategory_name:
                        subcategory.name = subcategory_name
                        changed = True

                    if subcategory.description != subcategory_description:
                        subcategory.description = subcategory_description
                        changed = True

                    if hasattr(subcategory, "is_active") and subcategory.is_active is not True:
                        subcategory.is_active = True
                        changed = True

                    if changed:
                        subcategories_updated += 1
                    else:
                        subcategories_existing += 1

                    if subcategory.code:
                        subcategories_by_code[
                            (
                                category.id,
                                subcategory.code.strip().upper(),
                            )
                        ] = subcategory

                    subcategories_by_name[
                        (
                            category.id,
                            subcategory.name.strip().lower(),
                        )
                    ] = subcategory

                else:
                    subcategory = ItemSubcategory(
                        category_id=category.id,
                        code=subcategory_code or None,
                        name=subcategory_name,
                        description=subcategory_description,
                    )

                    if hasattr(subcategory, "is_active"):
                        subcategory.is_active = True

                    db.session.add(subcategory)
                    db.session.flush()

                    if subcategory.code:
                        subcategories_by_code[
                            (
                                category.id,
                                subcategory.code.strip().upper(),
                            )
                        ] = subcategory

                    subcategories_by_name[
                        (
                            category.id,
                            subcategory.name.strip().lower(),
                        )
                    ] = subcategory

                    subcategories_created += 1

        except Exception as exc:
            db.session.rollback()

            print(
                f"[IMPORT_CATEGORIES_ERROR] "
                f"codigo={code} "
                f"nombre={name} "
                f"error={str(exc)}"
            )

            skipped += 1
            continue

    db.session.commit()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "subcategories_created": subcategories_created,
        "subcategories_updated": subcategories_updated,
        "subcategories_existing": subcategories_existing,
    }


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

    BATCH_SIZE = 300

    # =====================================================
    # NORMALIZAR FILAS PRIMERO
    # =====================================================
    normalized_rows = []

    for row in rows:
        code = _clean(row.get("codigo"))
        name = _clean(row.get("nombre"))
        unit_code = _clean(row.get("codigo_unidad"))

        if not code or not name or not unit_code:
            skipped += 1
            continue

        category_code = _clean(row.get("codigo_categoria"))
        category_name = _clean(row.get("nombre_categoria"))
        subcategory_name = _clean(row.get("nombre_subcategoria"))

        if category_name and not category_code:
            category_code = (
                category_name.strip().upper().replace(" ", "_")[:50]
            )

        normalized_rows.append(
            {
                "code": code,
                "name": name,
                "unit_code": unit_code,
                "category_code": category_code,
                "category_name": category_name,
                "subcategory_name": subcategory_name,
                "description": _clean(row.get("descripcion")) or None,
                "barcode": _clean(row.get("codigo_barras")) or None,
                "sap_code": _clean(row.get("codigo_sap")) or None,
                "is_tool": _parse_bool(row.get("es_herramienta")),
                "is_active": _parse_bool(row.get("activo")),
            }
        )

    if not normalized_rows:
        return {
            "created": created,
            "updated": updated,
            "skipped": skipped,
        }

    # =====================================================
    # PRECARGAS
    # =====================================================
    units_map = {u.code: u for u in Unit.query.all()}
    categories_map = {c.code: c for c in ItemCategory.query.all()}

    article_codes = {r["code"] for r in normalized_rows}
    barcode_values = {r["barcode"] for r in normalized_rows if r["barcode"]}

    existing_articles = (
        Article.query
        .filter(Article.code.in_(article_codes))
        .all()
    )

    articles_map = {a.code: a for a in existing_articles}

    barcodes_map = {}

    if barcode_values:
        existing_barcodes = (
            Article.query
            .filter(Article.barcode.in_(barcode_values))
            .all()
        )

        barcodes_map = {
            a.barcode: a
            for a in existing_barcodes
            if a.barcode
        }

    # =====================================================
    # CREAR CATEGORÍAS FALTANTES EN BLOQUE
    # =====================================================
    missing_categories = {}

    for row in normalized_rows:
        category_code = row["category_code"]
        category_name = row["category_name"]

        if category_code and category_code not in categories_map:
            missing_categories[category_code] = ItemCategory(
                code=category_code,
                name=category_name or category_code,
                description=None,
            )

    if missing_categories:
        db.session.add_all(missing_categories.values())
        db.session.flush()

        for category in missing_categories.values():
            categories_map[category.code] = category

    # =====================================================
    # PRECARGAR SUBCATEGORÍAS
    # =====================================================
    subcategories_map = {}

    for sc in ItemSubcategory.query.all():
        key = (sc.category_id, sc.name.strip().lower())
        subcategories_map[key] = sc

    # =====================================================
    # CREAR SUBCATEGORÍAS FALTANTES EN BLOQUE
    # =====================================================
    missing_subcategories = {}

    for row in normalized_rows:
        subcategory_name = row["subcategory_name"]
        category_code = row["category_code"]

        if not subcategory_name or not category_code:
            continue

        category = categories_map.get(category_code)

        if not category:
            continue

        key = (category.id, subcategory_name.strip().lower())

        if key not in subcategories_map and key not in missing_subcategories:
            missing_subcategories[key] = ItemSubcategory(
                category_id=category.id,
                name=subcategory_name,
            )

    if missing_subcategories:
        db.session.add_all(missing_subcategories.values())
        db.session.flush()

        for key, subcategory in missing_subcategories.items():
            subcategories_map[key] = subcategory

    # =====================================================
    # PROCESAR ARTÍCULOS
    # =====================================================
    processed = 0

    try:
        for row in normalized_rows:
            code = row["code"]
            name = row["name"]
            unit_code = row["unit_code"]
            barcode = row["barcode"]

            unit = units_map.get(unit_code)

            if not unit:
                skipped += 1
                continue

            category = None
            subcategory = None

            if row["category_code"]:
                category = categories_map.get(row["category_code"])

            if category and row["subcategory_name"]:
                sub_key = (
                    category.id,
                    row["subcategory_name"].strip().lower(),
                )
                subcategory = subcategories_map.get(sub_key)

            # =============================================
            # VALIDAR BARCODE DUPLICADO
            # =============================================
            if barcode:
                barcode_owner = barcodes_map.get(barcode)

                if barcode_owner and barcode_owner.code != code:
                    skipped += 1
                    continue

            article = articles_map.get(code)

            if article:
                article.name = name
                article.description = row["description"]
                article.unit_id = unit.id
                article.category_id = category.id if category else None
                article.subcategory_id = subcategory.id if subcategory else None
                article.barcode = barcode
                article.sap_code = row["sap_code"]
                article.is_tool = row["is_tool"]
                article.is_active = row["is_active"]

                updated += 1

            else:
                article = Article(
                    code=code,
                    name=name,
                    description=row["description"],
                    unit_id=unit.id,
                    category_id=category.id if category else None,
                    subcategory_id=subcategory.id if subcategory else None,
                    barcode=barcode,
                    sap_code=row["sap_code"],
                    is_tool=row["is_tool"],
                    is_active=row["is_active"],
                )

                db.session.add(article)
                articles_map[code] = article

                created += 1

            if barcode:
                barcodes_map[barcode] = article

            processed += 1

            if processed >= BATCH_SIZE:
                db.session.commit()
                processed = 0

        db.session.commit()

    except Exception as exc:
        db.session.rollback()
        raise Exception(f"Error en carga masiva de artículos: {exc}")

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }


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

    cleaned_rows = []

    for row in rows:
        try:
            warehouse_code = _clean(row.get("codigo_bodega"))
            article_code = _clean(row.get("codigo_articulo"))
            final_quantity = _parse_decimal(row.get("cantidad"), "cantidad")

            last_unit_cost_raw = _clean(row.get("ultimo_costo"))
            last_unit_cost = None

            if last_unit_cost_raw:
                last_unit_cost = _parse_decimal(
                    last_unit_cost_raw,
                    "ultimo_costo",
                )

            if not warehouse_code or not article_code:
                skipped += 1
                continue

            cleaned_rows.append(
                {
                    "warehouse_code": warehouse_code,
                    "article_code": article_code,
                    "final_quantity": final_quantity,
                    "last_unit_cost": last_unit_cost,
                }
            )

        except Exception:
            skipped += 1
            continue

    if not cleaned_rows:
        db.session.commit()
        return {"created": created, "updated": updated, "skipped": skipped}

    warehouse_codes = {row["warehouse_code"] for row in cleaned_rows}
    article_codes = {row["article_code"] for row in cleaned_rows}

    warehouses = (
        Warehouse.query
        .filter(
            Warehouse.site_id == site_id,
            Warehouse.code.in_(warehouse_codes),
        )
        .all()
    )

    articles = (
        Article.query
        .filter(Article.code.in_(article_codes))
        .all()
    )

    warehouses_map = {warehouse.code: warehouse for warehouse in warehouses}
    articles_map = {article.code: article for article in articles}

    warehouse_ids = [warehouse.id for warehouse in warehouses]
    article_ids = [article.id for article in articles]

    existing_stocks = []

    if warehouse_ids and article_ids:
        existing_stocks = (
            WarehouseStock.query
            .filter(
                WarehouseStock.warehouse_id.in_(warehouse_ids),
                WarehouseStock.article_id.in_(article_ids),
            )
            .all()
        )

    stocks_map = {
        (stock.warehouse_id, stock.article_id): stock
        for stock in existing_stocks
    }

    for row in cleaned_rows:
        try:
            warehouse = warehouses_map.get(row["warehouse_code"])
            article = articles_map.get(row["article_code"])

            if not warehouse or not article:
                skipped += 1
                continue

            final_quantity = row["final_quantity"]
            last_unit_cost = row["last_unit_cost"]

            stock_key = (warehouse.id, article.id)
            stock = stocks_map.get(stock_key)

            if not stock:
                stock = WarehouseStock(
                    warehouse_id=warehouse.id,
                    article_id=article.id,
                    reserved_quantity=Decimal("0"),
                )

                _set_quantity_on_hand(stock, Decimal("0"))

                if hasattr(stock, "last_unit_cost"):
                    stock.last_unit_cost = last_unit_cost

                db.session.add(stock)
                stocks_map[stock_key] = stock
                created += 1

            if last_unit_cost is not None and hasattr(stock, "last_unit_cost"):
                stock.last_unit_cost = last_unit_cost

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

def import_article_suppliers(rows: list[dict]):
    created = 0
    existing = 0
    articles_created = 0
    suppliers_created = 0

    # ⚠️ unidad por defecto (VALIDAR QUE EXISTA EN BD)
    default_unit = Unit.query.filter_by(code="UND").first()
    if not default_unit:
        raise Exception("No existe unidad 'UND' en la BD.")

    for row in rows:
        codigo = str(row.get("codigo_articulo", "")).strip()
        nombre = str(row.get("nombre_articulo", "")).strip()

        if not codigo:
            continue

        # =========================
        # ARTÍCULO
        # =========================
        article = Article.query.filter_by(code=codigo).first()

        if not article:
            if not nombre:
                continue

            article = Article(
                code=codigo,
                name=nombre,
                unit_id=default_unit.id,
            )
            db.session.add(article)
            db.session.flush()
            articles_created += 1

        # =========================
        # PROVEEDORES
        # =========================
        for i in range(1, 11):
            proveedor_nombre = str(row.get(f"proveedor_{i}", "")).strip()

            if not proveedor_nombre:
                continue

            supplier = Supplier.query.filter_by(
                commercial_name=proveedor_nombre
            ).first()

            if not supplier:
                supplier = Supplier(
                    commercial_name=proveedor_nombre,
                )
                db.session.add(supplier)
                db.session.flush()
                suppliers_created += 1

            # =========================
            # RELACIÓN
            # =========================
            relation = ArticleSupplier.query.filter_by(
                article_id=article.id,
                supplier_id=supplier.id,
            ).first()

            if relation:
                existing += 1
                continue

            relation = ArticleSupplier(
                article_id=article.id,
                supplier_id=supplier.id,
            )
            db.session.add(relation)
            created += 1

    db.session.commit()

    return {
        "created": created,
        "existing": existing,
        "articles_created": articles_created,
        "suppliers_created": suppliers_created,
    }

# =========================================================
# ARTÍCULOS - ACTUALIZAR SOLO CATEGORÍA / SUBCATEGORÍA
# =========================================================
def import_article_categories(rows: list[dict]) -> dict:
    updated = 0
    skipped = 0
    not_found = 0

    normalized_rows = []

    for row in rows:
        code = _clean(row.get("codigo"))
        category_code = _clean(row.get("codigo_categoria"))
        category_name = _clean(row.get("nombre_categoria"))
        subcategory_name = _clean(row.get("nombre_subcategoria"))

        if not code:
            skipped += 1
            continue

        if category_name and not category_code:
            category_code = category_name.strip().upper().replace(" ", "_")[:50]

        if not category_code and not category_name and not subcategory_name:
            skipped += 1
            continue

        normalized_rows.append({
            "code": code,
            "category_code": category_code,
            "category_name": category_name,
            "subcategory_name": subcategory_name,
        })

    if not normalized_rows:
        return {
            "updated": updated,
            "skipped": skipped,
            "not_found": not_found,
        }

    article_codes = {r["code"] for r in normalized_rows}

    articles_map = {
        a.code: a
        for a in Article.query.filter(Article.code.in_(article_codes)).all()
    }

    categories_map = {
        c.code: c
        for c in ItemCategory.query.all()
    }

    # Crear categorías faltantes
    missing_categories = {}

    for row in normalized_rows:
        category_code = row["category_code"]
        category_name = row["category_name"]

        if category_code and category_code not in categories_map:
            missing_categories[category_code] = ItemCategory(
                code=category_code,
                name=category_name or category_code,
                description=None,
            )

    if missing_categories:
        db.session.add_all(missing_categories.values())
        db.session.flush()

        for category in missing_categories.values():
            categories_map[category.code] = category

    subcategories_map = {
        (sc.category_id, sc.name.strip().lower()): sc
        for sc in ItemSubcategory.query.all()
    }

    # Crear subcategorías faltantes
    missing_subcategories = {}

    for row in normalized_rows:
        category_code = row["category_code"]
        subcategory_name = row["subcategory_name"]

        if not category_code or not subcategory_name:
            continue

        category = categories_map.get(category_code)

        if not category:
            continue

        key = (category.id, subcategory_name.strip().lower())

        if key not in subcategories_map and key not in missing_subcategories:
            missing_subcategories[key] = ItemSubcategory(
                category_id=category.id,
                name=subcategory_name,
            )

    if missing_subcategories:
        db.session.add_all(missing_subcategories.values())
        db.session.flush()

        for key, subcategory in missing_subcategories.items():
            subcategories_map[key] = subcategory

    # Actualizar solo artículos existentes
    for row in normalized_rows:
        article = articles_map.get(row["code"])

        if not article:
            not_found += 1
            continue

        category = None
        subcategory = None

        if row["category_code"]:
            category = categories_map.get(row["category_code"])

        if category and row["subcategory_name"]:
            key = (
                category.id,
                row["subcategory_name"].strip().lower(),
            )
            subcategory = subcategories_map.get(key)

        article.category_id = category.id if category else None
        article.subcategory_id = subcategory.id if subcategory else None

        updated += 1

    db.session.commit()

    return {
        "updated": updated,
        "skipped": skipped,
        "not_found": not_found,
    }