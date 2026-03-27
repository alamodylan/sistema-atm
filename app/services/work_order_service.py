from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.extensions import db
from app.models.article import Article
from app.models.user import User
from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLine
from app.services.audit_service import log_action
from app.services.inventory_service import InventoryServiceError, subtract_stock


class WorkOrderServiceError(Exception):
    pass


def create_work_order(
    *,
    number: str,
    site_id: int,
    warehouse_id: int,
    responsible_user_id: int,
    created_by_user_id: int,
    mechanic_ids: list[int],
    description: str | None = None,
    equipment_id: int | None = None,
    equipment_code_snapshot: str | None = None,
    commit: bool = True,
) -> WorkOrder:
    if not number.strip():
        raise WorkOrderServiceError("El número de OT es obligatorio.")

    if not site_id:
        raise WorkOrderServiceError("El predio es obligatorio.")

    if not warehouse_id:
        raise WorkOrderServiceError("La bodega es obligatoria.")

    if not responsible_user_id:
        raise WorkOrderServiceError("El responsable es obligatorio.")

    if not mechanic_ids:
        raise WorkOrderServiceError("Debe seleccionar al menos un mecánico.")

    existing = WorkOrder.query.filter_by(number=number.strip()).first()
    if existing:
        raise WorkOrderServiceError("Ya existe una orden de trabajo con ese número.")

    mechanics = User.query.filter(User.id.in_(mechanic_ids)).all()
    if len(mechanics) != len(set(mechanic_ids)):
        raise WorkOrderServiceError("Uno o más mecánicos seleccionados no existen.")

    work_order = WorkOrder(
        number=number.strip(),
        status="EN_PROCESO",
        site_id=site_id,
        warehouse_id=warehouse_id,
        responsible_user_id=responsible_user_id,
        created_by_user_id=created_by_user_id,
        description=(description or "").strip() or None,
        equipment_id=equipment_id,
        equipment_code_snapshot=equipment_code_snapshot,
    )

    work_order.mechanics = mechanics

    db.session.add(work_order)

    if commit:
        db.session.commit()

    log_action(
        user_id=created_by_user_id,
        action="CREATE_WORK_ORDER",
        table_name="work_orders",
        record_id=str(work_order.id),
        details={
            "number": work_order.number,
            "site_id": site_id,
            "warehouse_id": warehouse_id,
            "responsible_user_id": responsible_user_id,
            "mechanic_ids": mechanic_ids,
            "equipment_id": equipment_id,
        },
        commit=commit,
    )

    return work_order


def add_work_order_line(
    *,
    work_order_id: int,
    article_id: int,
    quantity: Decimal | int | float,
    delivered_by_user_id: int,
    received_by_user_id: int | None = None,
    notes: str | None = None,
    commit: bool = True,
) -> WorkOrderLine:
    work_order = WorkOrder.query.get(work_order_id)
    if not work_order:
        raise WorkOrderServiceError("La OT no existe.")

    if work_order.status != "EN_PROCESO":
        raise WorkOrderServiceError("Solo se pueden agregar líneas a una OT en proceso.")

    article = Article.query.get(article_id)
    if not article:
        raise WorkOrderServiceError("El artículo no existe.")

    qty = Decimal(str(quantity))
    if qty <= 0:
        raise WorkOrderServiceError("La cantidad debe ser mayor a 0.")

    try:
        subtract_stock(
            article_id=article_id,
            warehouse_id=work_order.warehouse_id,
            quantity=qty,
            performed_by_user_id=delivered_by_user_id,
            movement_type="SALIDA_OT",
            reason=f"Salida por OT {work_order.number}",
            reference_type="WORK_ORDER",
            reference_id=work_order.id,
            reference_number=work_order.number,
            commit=False,
        )
    except InventoryServiceError as exc:
        db.session.rollback()
        raise WorkOrderServiceError(str(exc)) from exc

    line = WorkOrderLine(
        work_order_id=work_order.id,
        article_id=article_id,
        quantity=qty,
        delivered_by_user_id=delivered_by_user_id,
        received_by_user_id=received_by_user_id,
        line_status="ACTIVE",
        inventory_posted=True,
        notes=(notes or "").strip() or None,
        delivered_at=datetime.now(UTC),
        received_at=datetime.now(UTC) if received_by_user_id else None,
    )

    db.session.add(line)

    if commit:
        db.session.commit()

    log_action(
        user_id=delivered_by_user_id,
        action="ADD_WORK_ORDER_LINE",
        table_name="work_order_lines",
        record_id=str(line.id),
        details={
            "work_order_id": work_order.id,
            "article_id": article_id,
            "quantity": str(qty),
            "movement_type": "SALIDA_OT",
        },
        commit=commit,
    )

    return line


def finalize_work_order(
    *,
    work_order_id: int,
    performed_by_user_id: int,
    has_loaned_tools: bool = False,
    commit: bool = True,
) -> WorkOrder:
    work_order = WorkOrder.query.get(work_order_id)
    if not work_order:
        raise WorkOrderServiceError("La OT no existe.")

    if work_order.status != "EN_PROCESO":
        raise WorkOrderServiceError("Solo se puede finalizar una OT en proceso.")

    if has_loaned_tools:
        raise WorkOrderServiceError("No se puede finalizar la OT porque tiene herramientas prestadas.")

    for line in work_order.lines:
        if line.delete_requests.filter_by(status="PENDIENTE").first():
            raise WorkOrderServiceError(
                "No se puede finalizar la OT porque tiene solicitudes de eliminación pendientes."
            )

    work_order.status = "FINALIZADA"
    work_order.finalized_at = datetime.now(UTC)

    if commit:
        db.session.commit()

    log_action(
        user_id=performed_by_user_id,
        action="FINALIZE_WORK_ORDER",
        table_name="work_orders",
        record_id=str(work_order.id),
        details={"status": work_order.status},
        commit=commit,
    )

    return work_order


def close_work_order(
    *,
    work_order_id: int,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrder:
    work_order = WorkOrder.query.get(work_order_id)
    if not work_order:
        raise WorkOrderServiceError("La OT no existe.")

    if work_order.status != "FINALIZADA":
        raise WorkOrderServiceError("No se puede cerrar la OT si no está finalizada.")

    work_order.status = "CERRADA"
    work_order.closed_at = datetime.now(UTC)

    if commit:
        db.session.commit()

    log_action(
        user_id=performed_by_user_id,
        action="CLOSE_WORK_ORDER",
        table_name="work_orders",
        record_id=str(work_order.id),
        details={"status": work_order.status},
        commit=commit,
    )

    return work_order