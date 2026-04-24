from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.extensions import db
from app.models.tool_loan import ToolLoan
from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLine
from app.models.work_order_request_line import WorkOrderRequestLine
from app.services.audit_service import log_action
from app.services.inventory_service import InventoryServiceError, subtract_stock
from app.services.work_order_task_service import create_task_line


class WorkOrderServiceError(Exception):
    pass


def _generate_next_work_order_number() -> str:
    last_work_order = WorkOrder.query.order_by(WorkOrder.id.desc()).first()

    if not last_work_order:
        return "1"

    last_number = (last_work_order.number or "").strip()

    if last_number.isdigit():
        return str(int(last_number) + 1)

    numeric_orders = (
        WorkOrder.query
        .filter(WorkOrder.number.isnot(None))
        .order_by(WorkOrder.id.desc())
        .all()
    )

    for work_order in numeric_orders:
        current_number = (work_order.number or "").strip()
        if current_number.isdigit():
            return str(int(current_number) + 1)

    return "1"


def create_work_order(
    *,
    number: str,
    site_id: int,
    warehouse_id: int,
    responsible_user_id: int,
    created_by_user_id: int,
    repair_type_id: int,
    mechanic_id: int,
    task_title: str,
    task_description: str | None = None,
    description: str | None = None,
    equipment_id: int | None = None,
    equipment_code_snapshot: str | None = None,
    commit: bool = True,
) -> WorkOrder:
    generated_number = _generate_next_work_order_number()

    if not site_id:
        raise WorkOrderServiceError("El predio es obligatorio.")

    if not warehouse_id:
        raise WorkOrderServiceError("La bodega es obligatoria.")

    if not responsible_user_id:
        raise WorkOrderServiceError("El responsable es obligatorio.")

    if not repair_type_id:
        raise WorkOrderServiceError("Debe seleccionar un tipo de reparación.")

    if not mechanic_id:
        raise WorkOrderServiceError("Debe seleccionar un mecánico.")

    if not task_title or not task_title.strip():
        raise WorkOrderServiceError("Debe indicar el trabajo a realizar.")

    existing = WorkOrder.query.filter_by(number=generated_number).first()
    if existing:
        raise WorkOrderServiceError("Ya existe una orden de trabajo con ese número.")

    work_order = WorkOrder(
        number=generated_number,
        status="EN_PROCESO",
        site_id=site_id,
        warehouse_id=warehouse_id,
        responsible_user_id=responsible_user_id,
        created_by_user_id=created_by_user_id,
        description=(description or "").strip() or None,
        equipment_id=equipment_id,
        equipment_code_snapshot=(equipment_code_snapshot or "").strip() or None,
    )

    db.session.add(work_order)
    db.session.flush()

    create_task_line(
        work_order_id=work_order.id,
        repair_type_id=repair_type_id,
        title=task_title.strip(),
        description=(task_description or "").strip() or None,
        assigned_mechanic_id=mechanic_id,
        created_by_user_id=created_by_user_id,
        commit=False,
    )

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
            "equipment_id": equipment_id,
            "repair_type_id": repair_type_id,
            "mechanic_id": mechanic_id,
            "task_title": task_title,
        },
        commit=commit,
    )

    return work_order


def deliver_from_request_line(
    *,
    request_line_id: int,
    quantity,
    delivered_by_user_id: int,
    received_by_user_id: int | None = None,
    commit: bool = True,
) -> WorkOrderLine:

    request_line = WorkOrderRequestLine.query.get(request_line_id)
    if not request_line:
        raise WorkOrderServiceError("La línea de solicitud no existe.")

    work_order = request_line.work_order_request.work_order

    if work_order.status != "EN_PROCESO":
        raise WorkOrderServiceError("La OT no está en proceso.")

    qty = Decimal(str(quantity))
    if qty <= 0:
        raise WorkOrderServiceError("Cantidad inválida.")

    remaining = request_line.quantity_requested - request_line.quantity_attended
    if qty > remaining:
        raise WorkOrderServiceError("No puede entregar más de lo solicitado.")

    try:
        subtract_stock(
            article_id=request_line.article_id,
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

    request_line.quantity_attended += qty

    if request_line.quantity_attended == request_line.quantity_requested:
        request_line.line_status = "ENTREGADA"
    else:
        request_line.line_status = "ATENDIDA_PARCIAL"

    line = WorkOrderLine(
        work_order_id=work_order.id,
        request_line_id=request_line.id,
        article_id=request_line.article_id,
        quantity=qty,
        delivered_by_user_id=delivered_by_user_id,
        received_by_user_id=received_by_user_id,
        line_status="ACTIVE",
        inventory_posted=True,
        delivered_at=datetime.now(UTC),
        received_at=datetime.now(UTC) if received_by_user_id else None,
    )

    db.session.add(line)

    if commit:
        db.session.commit()

    log_action(
        user_id=delivered_by_user_id,
        action="DELIVER_FROM_REQUEST",
        table_name="work_order_lines",
        record_id=str(line.id),
        details={
            "request_line_id": request_line.id,
            "quantity": str(qty),
        },
        commit=commit,
    )

    return line


def finalize_work_order(
    *,
    work_order_id: int,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrder:

    work_order = WorkOrder.query.get(work_order_id)
    if not work_order:
        raise WorkOrderServiceError("La OT no existe.")

    if work_order.status != "EN_PROCESO":
        raise WorkOrderServiceError("Solo se puede finalizar una OT en proceso.")

    has_open_loans = ToolLoan.query.filter_by(
        work_order_id=work_order_id,
        loan_status="PRESTADA",
    ).count() > 0

    if has_open_loans:
        raise WorkOrderServiceError(
            "No se puede finalizar la OT porque tiene herramientas prestadas."
        )

    pending_tasks = [
        task_line
        for task_line in work_order.task_lines
        if task_line.status not in ("FINALIZADA", "CANCELADA")
    ]

    if pending_tasks:
        raise WorkOrderServiceError(
            "No se puede finalizar la OT porque tiene trabajos pendientes."
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