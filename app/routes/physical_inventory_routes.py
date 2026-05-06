from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from app.utils.permissions import permission_required

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.physical_inventory import PhysicalInventory
from app.models.physical_inventory_line import PhysicalInventoryLine
from app.models.warehouse import Warehouse
from app.models.inventory import WarehouseStock
from app.services.physical_inventory_service import apply_physical_inventory_adjustment


physical_inventory_bp = Blueprint(
    "physical_inventory",
    __name__,
    url_prefix="/physical-inventory",
)


class PhysicalInventoryRouteError(Exception):
    pass


def _to_decimal(value, default="0") -> Decimal:
    try:
        raw = str(value if value is not None else default).strip()
        return Decimal(raw if raw else default)
    except (InvalidOperation, TypeError):
        raise PhysicalInventoryRouteError("Cantidad inválida.")


def _generate_inventory_number() -> str:
    last_id = db.session.query(db.func.max(PhysicalInventory.id)).scalar() or 0
    return f"IF-{int(last_id) + 1:06d}"


@physical_inventory_bp.route("/")
@login_required
@permission_required("inventario_fisico")
def index():
    active_site_id = session.get("active_site_id")

    query = PhysicalInventory.query

    if active_site_id:
        query = query.filter(PhysicalInventory.site_id == int(active_site_id))

    inventories = (
        query
        .order_by(
            PhysicalInventory.created_at.desc(),
            PhysicalInventory.id.desc(),
        )
        .all()
    )

    warehouses_query = Warehouse.query.filter(Warehouse.is_active.is_(True))

    if active_site_id:
        warehouses_query = warehouses_query.filter(Warehouse.site_id == int(active_site_id))

    warehouses = warehouses_query.order_by(Warehouse.name.asc()).all()

    return render_template(
        "physical_inventory/index.html",
        inventories=inventories,
        warehouses=warehouses,
    )


@physical_inventory_bp.route("/create", methods=["POST"])
@login_required
def create():
    active_site_id = session.get("active_site_id")
    warehouse_id = request.form.get("warehouse_id")

    if not active_site_id:
        flash("Debe seleccionar un predio activo antes de crear un inventario físico.", "danger")
        return redirect(url_for("physical_inventory.index"))

    if not warehouse_id:
        flash("Debe seleccionar una bodega.", "danger")
        return redirect(url_for("physical_inventory.index"))

    warehouse = Warehouse.query.filter(
        Warehouse.id == int(warehouse_id),
        Warehouse.site_id == int(active_site_id),
        Warehouse.is_active.is_(True),
    ).first()

    if not warehouse:
        flash("La bodega seleccionada no pertenece al predio activo o no está activa.", "danger")
        return redirect(url_for("physical_inventory.index"))

    existing_open = PhysicalInventory.query.filter(
        PhysicalInventory.warehouse_id == warehouse.id,
        PhysicalInventory.status.in_(["BORRADOR", "EN_CONTEO"]),
    ).first()

    if existing_open:
        flash(
            f"Ya existe un inventario físico abierto para esta bodega: {existing_open.number}.",
            "warning",
        )
        return redirect(
            url_for("physical_inventory.detail", inventory_id=existing_open.id)
        )

    stock_items = (
        WarehouseStock.query
        .filter(WarehouseStock.warehouse_id == warehouse.id)
        .order_by(WarehouseStock.article_id.asc())
        .all()
    )

    if not stock_items:
        flash("La bodega seleccionada no tiene stock registrado.", "warning")
        return redirect(url_for("physical_inventory.index"))

    inventory = PhysicalInventory(
        number=_generate_inventory_number(),
        site_id=int(active_site_id),
        warehouse_id=warehouse.id,
        created_by_user_id=current_user.id,
        status="EN_CONTEO",
        notes=request.form.get("notes"),
        created_at=datetime.now(UTC),
    )

    db.session.add(inventory)
    db.session.flush()

    lines_to_insert = []

    for stock in stock_items:
        quantity_on_hand = getattr(stock, "quantity_on_hand", None)

        if quantity_on_hand is None:
            quantity_on_hand = getattr(stock, "quantity", Decimal("0"))

        lines_to_insert.append(
            PhysicalInventoryLine(
                physical_inventory_id=inventory.id,
                article_id=stock.article_id,
                system_quantity=quantity_on_hand or Decimal("0"),
                physical_quantity=None,
                difference_quantity=None,
            )
        )

    db.session.bulk_save_objects(lines_to_insert)
    db.session.commit()
    flash("Inventario físico creado correctamente.", "success")
    return redirect(url_for("physical_inventory.detail", inventory_id=inventory.id))


@physical_inventory_bp.route("/<int:inventory_id>")
@login_required
def detail(inventory_id: int):
    inventory = PhysicalInventory.query.get_or_404(inventory_id)

    active_site_id = session.get("active_site_id")
    if active_site_id and inventory.site_id != int(active_site_id):
        flash("Este inventario físico no pertenece al predio activo.", "danger")
        return redirect(url_for("physical_inventory.index"))

    lines = (
        PhysicalInventoryLine.query
        .filter(PhysicalInventoryLine.physical_inventory_id == inventory.id)
        .join(PhysicalInventoryLine.article)
        .order_by(
            db.text("atm.articles.code ASC"),
            PhysicalInventoryLine.id.asc(),
        )
        .all()
    )

    return render_template(
        "physical_inventory/detail.html",
        inventory=inventory,
        lines=lines,
    )


@physical_inventory_bp.route("/update-line", methods=["POST"])
@login_required
def update_line():
    data = request.get_json(silent=True) or {}

    line_id = data.get("line_id")
    physical_quantity_raw = data.get("physical_quantity")

    if not line_id:
        return {"ok": False, "message": "No se recibió la línea."}, 400

    line = PhysicalInventoryLine.query.get_or_404(int(line_id))
    inventory = line.physical_inventory

    if inventory.status not in ["BORRADOR", "EN_CONTEO"]:
        return {
            "ok": False,
            "message": "Este inventario físico ya no permite modificaciones.",
        }, 400

    try:
        physical_quantity = _to_decimal(physical_quantity_raw)
    except PhysicalInventoryRouteError as exc:
        return {"ok": False, "message": str(exc)}, 400

    if physical_quantity < 0:
        return {"ok": False, "message": "La cantidad física no puede ser negativa."}, 400

    system_quantity = line.system_quantity or Decimal("0")
    difference_quantity = physical_quantity - system_quantity

    line.physical_quantity = physical_quantity
    line.difference_quantity = difference_quantity
    line.counted_at = datetime.now(UTC)

    db.session.commit()

    return {
        "ok": True,
        "line_id": line.id,
        "system_quantity": str(system_quantity),
        "physical_quantity": str(physical_quantity),
        "difference_quantity": str(difference_quantity),
    }


@physical_inventory_bp.route("/<int:inventory_id>/close", methods=["POST"])
@login_required
def close(inventory_id: int):
    inventory = PhysicalInventory.query.get_or_404(inventory_id)

    if inventory.status not in ["BORRADOR", "EN_CONTEO"]:
        flash("Este inventario físico no se puede cerrar en su estado actual.", "warning")
        return redirect(url_for("physical_inventory.detail", inventory_id=inventory.id))

    total_lines = PhysicalInventoryLine.query.filter(
        PhysicalInventoryLine.physical_inventory_id == inventory.id
    ).count()

    counted_lines = PhysicalInventoryLine.query.filter(
        PhysicalInventoryLine.physical_inventory_id == inventory.id,
        PhysicalInventoryLine.physical_quantity.isnot(None),
    ).count()

    if total_lines != counted_lines:
        flash(
            f"No se puede cerrar. Faltan líneas por contar: {total_lines - counted_lines}.",
            "danger",
        )
        return redirect(url_for("physical_inventory.detail", inventory_id=inventory.id))

    inventory.status = "FINALIZADO"
    db.session.commit()

    flash("Inventario físico cerrado correctamente.", "success")
    return redirect(url_for("physical_inventory.detail", inventory_id=inventory.id))


@physical_inventory_bp.route("/<int:inventory_id>/apply-adjustment", methods=["POST"])
@login_required
def apply_adjustment(inventory_id: int):
    inventory = PhysicalInventory.query.get_or_404(inventory_id)

    # 🔒 Validación de estado
    if inventory.status != "FINALIZADO":
        flash("El inventario debe estar FINALIZADO antes de aplicar ajustes.", "danger")
        return redirect(url_for("physical_inventory.detail", inventory_id=inventory.id))

    # 🔒 Confirmación fuerte
    confirmation = request.form.get("confirmation_text", "").strip().upper()

    if confirmation != "AJUSTAR INVENTARIO":
        flash(
            "Debe escribir exactamente 'AJUSTAR INVENTARIO' para confirmar.",
            "danger",
        )
        return redirect(url_for("physical_inventory.detail", inventory_id=inventory.id))

    try:
        apply_physical_inventory_adjustment(
            inventory_id=inventory.id,
            user_id=current_user.id,
        )

        flash("Inventario ajustado correctamente.", "success")

    except Exception as e:
        flash(f"Error al aplicar ajuste: {str(e)}", "danger")

    return redirect(url_for("physical_inventory.detail", inventory_id=inventory.id))