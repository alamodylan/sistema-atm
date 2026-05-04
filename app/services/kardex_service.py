# app/services/kardex_service.py

from decimal import Decimal
from sqlalchemy import func

from app.extensions import db
from app.models.inventory import InventoryLedger
from app.models.warehouse import Warehouse
from app.models.article import Article
from app.models.user import User


class KardexServiceError(Exception):
    pass


def get_article_by_code_or_barcode(code):
    article = (
        Article.query
        .filter(
            db.or_(
                Article.code == code,
                Article.barcode == code
            )
        )
        .first()
    )

    if not article:
        raise KardexServiceError("Artículo no encontrado.")

    return article


def get_kardex_warehouses_for_site(site_id):
    return (
        Warehouse.query
        .filter(
            Warehouse.site_id == site_id,
            Warehouse.is_active.is_(True)
        )
        .order_by(Warehouse.name.asc())
        .all()
    )


def get_kardex_data(
    *,
    site_id,
    warehouse_id,
    article_id,
    date_from,
    date_to
):
    # 🔹 Validar bodega pertenece al predio
    warehouse = Warehouse.query.get(warehouse_id)

    if not warehouse:
        raise KardexServiceError("La bodega no existe.")

    if warehouse.site_id != site_id:
        raise KardexServiceError("La bodega no pertenece al predio activo.")

    # 🔹 Saldo inicial
    initial_balance = (
        db.session.query(func.coalesce(func.sum(InventoryLedger.quantity_change), 0))
        .filter(
            InventoryLedger.warehouse_id == warehouse_id,
            InventoryLedger.article_id == article_id,
            InventoryLedger.created_at < date_from
        )
        .scalar()
    )

    initial_balance = Decimal(initial_balance or 0)

    # 🔹 Movimientos
    movements = (
        InventoryLedger.query
        .filter(
            InventoryLedger.warehouse_id == warehouse_id,
            InventoryLedger.article_id == article_id,
            InventoryLedger.created_at >= date_from,
            InventoryLedger.created_at <= date_to
        )
        .order_by(
            InventoryLedger.created_at.asc(),
            InventoryLedger.id.asc()
        )
        .all()
    )

    running_balance = initial_balance
    kardex_lines = []

    for m in movements:
        quantity = Decimal(m.quantity_change or 0)
        running_balance += quantity

        # 🔹 Resolver bodega destino/origen
        related_warehouse_name = None
        if m.related_warehouse_id:
            related = Warehouse.query.get(m.related_warehouse_id)
            related_warehouse_name = related.name if related else None

        # 🔹 Usuario
        user_name = None
        if m.performed_by_user_id:
            user = User.query.get(m.performed_by_user_id)
            user_name = user.username if user else None

        kardex_lines.append({
            "date": m.created_at,
            "movement_type": m.movement_type,
            "reference": m.reference_number,
            "reference_type": m.reference_type,
            "quantity": quantity,
            "unit_cost": m.unit_cost,
            "total_cost": m.total_cost,
            "balance": running_balance,
            "warehouse_name": warehouse.name,
            "related_warehouse_name": related_warehouse_name,
            "notes": m.notes,
            "user": user_name
        })

    final_balance = running_balance

    return {
        "initial_balance": initial_balance,
        "final_balance": final_balance,
        "lines": kardex_lines
    }