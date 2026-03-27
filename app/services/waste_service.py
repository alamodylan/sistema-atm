from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models.waste_act import WasteAct
from app.models.waste_act_line import WasteActLine
from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLine
from app.services.audit_service import log_action


class WasteServiceError(Exception):
    pass


def create_waste_act(
    *,
    number: str,
    site_id: int,
    warehouse_id: int,
    date_from,
    date_to,
    created_by_user_id: int,
    notes: str | None = None,
    commit: bool = True,
) -> WasteAct:
    if not number or not number.strip():
        raise WasteServiceError("El número del acta es obligatorio.")

    if not site_id:
        raise WasteServiceError("El predio es obligatorio.")

    if not warehouse_id:
        raise WasteServiceError("La bodega es obligatoria.")

    if not date_from or not date_to:
        raise WasteServiceError("El rango de fechas es obligatorio.")

    existing = WasteAct.query.filter_by(number=number.strip()).first()
    if existing:
        raise WasteServiceError("Ya existe un acta de desecho con ese número.")

    waste_act = WasteAct(
        number=number.strip(),
        site_id=site_id,
        warehouse_id=warehouse_id,
        date_from=date_from,
        date_to=date_to,
        status="BORRADOR",
        notes=(notes or "").strip() or None,
        created_by_user_id=created_by_user_id,
    )

    db.session.add(waste_act)
    db.session.flush()

    log_action(
        user_id=created_by_user_id,
        action="CREATE_WASTE_ACT",
        table_name="waste_acts",
        record_id=str(waste_act.id),
        details={
            "number": waste_act.number,
            "site_id": waste_act.site_id,
            "warehouse_id": waste_act.warehouse_id,
            "date_from": str(waste_act.date_from),
            "date_to": str(waste_act.date_to),
            "status": waste_act.status,
        },
        commit=False,
    )

    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    return waste_act


def get_waste_candidates(
    *,
    date_from,
    date_to,
    site_id: int | None = None,
    warehouse_id: int | None = None,
) -> list[WorkOrderLine]:
    query = (
        WorkOrderLine.query
        .join(WorkOrder, WorkOrder.id == WorkOrderLine.work_order_id)
        .filter(WorkOrderLine.quantity > 0)
        .filter(WorkOrderLine.inventory_posted.is_(True))
        .filter(WorkOrderLine.line_status == "ACTIVE")
        .filter(WorkOrderLine.delivered_at >= date_from)
        .filter(WorkOrderLine.delivered_at <= date_to)
        .filter(~WorkOrderLine.waste_act_lines.any())
    )

    if site_id:
        query = query.filter(WorkOrder.site_id == site_id)

    if warehouse_id:
        query = query.filter(WorkOrder.warehouse_id == warehouse_id)

    return query.order_by(WorkOrderLine.delivered_at.asc(), WorkOrderLine.id.asc()).all()


def add_line_to_waste_act(
    *,
    waste_act_id: int,
    work_order_line_id: int,
    quantity: Decimal | int | float,
    confirmed_for_disposal: bool,
    notes: str | None,
    performed_by_user_id: int,
    commit: bool = True,
) -> WasteActLine:
    waste_act = WasteAct.query.get(waste_act_id)
    if not waste_act:
        raise WasteServiceError("El acta de desecho no existe.")

    if waste_act.status != "BORRADOR":
        raise WasteServiceError("Solo se pueden agregar líneas a un acta en estado BORRADOR.")

    line = WorkOrderLine.query.get(work_order_line_id)
    if not line:
        raise WasteServiceError("La línea de OT no existe.")

    if line.line_status != "ACTIVE":
        raise WasteServiceError("Solo se pueden usar líneas activas.")

    if not line.inventory_posted:
        raise WasteServiceError("La línea no impactó inventario, no aplica para desecho.")

    if line.work_order is None:
        raise WasteServiceError("La línea no tiene una OT asociada válida.")

    if line.work_order.site_id != waste_act.site_id:
        raise WasteServiceError("La línea no pertenece al mismo predio del acta de desecho.")

    if line.work_order.warehouse_id != waste_act.warehouse_id:
        raise WasteServiceError("La línea no pertenece a la misma bodega del acta de desecho.")

    existing_any = WasteActLine.query.filter_by(work_order_line_id=work_order_line_id).first()
    if existing_any:
        raise WasteServiceError("La línea ya fue agregada a un acta de desecho.")

    qty = Decimal(str(quantity))
    line_qty = Decimal(str(line.quantity or 0))

    if qty <= 0:
        raise WasteServiceError("La cantidad debe ser mayor a cero.")

    if qty > line_qty:
        raise WasteServiceError("La cantidad no puede ser mayor a la registrada en la línea.")

    waste_line = WasteActLine(
        waste_act_id=waste_act.id,
        work_order_id=line.work_order_id,
        work_order_line_id=line.id,
        article_id=line.article_id,
        quantity=qty,
        confirmed_for_disposal=confirmed_for_disposal,
        notes=(notes or "").strip() or None,
    )

    db.session.add(waste_line)
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="ADD_WASTE_ACT_LINE",
        table_name="waste_act_lines",
        record_id=str(waste_line.id),
        details={
            "waste_act_id": waste_act.id,
            "work_order_id": line.work_order_id,
            "work_order_line_id": line.id,
            "article_id": line.article_id,
            "quantity": str(qty),
            "confirmed_for_disposal": confirmed_for_disposal,
        },
        commit=False,
    )

    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    return waste_line


def change_waste_act_status(
    *,
    waste_act_id: int,
    new_status: str,
    performed_by_user_id: int,
    commit: bool = True,
) -> WasteAct:
    allowed_statuses = {"BORRADOR", "REGISTRADA", "IMPRESA", "CERRADA", "CANCELADA"}

    transitions = {
        "BORRADOR": {"REGISTRADA", "CANCELADA"},
        "REGISTRADA": {"IMPRESA", "CANCELADA"},
        "IMPRESA": {"CERRADA"},
        "CERRADA": set(),
        "CANCELADA": set(),
    }

    if new_status not in allowed_statuses:
        raise WasteServiceError("El estado solicitado no es válido.")

    waste_act = WasteAct.query.get(waste_act_id)
    if not waste_act:
        raise WasteServiceError("El acta de desecho no existe.")

    previous_status = waste_act.status

    if previous_status == new_status:
        return waste_act

    if new_status not in transitions.get(previous_status, set()):
        raise WasteServiceError(
            f"No se puede cambiar el acta de {previous_status} a {new_status}."
        )

    if new_status in {"REGISTRADA", "IMPRESA", "CERRADA"} and waste_act.lines.count() == 0:
        raise WasteServiceError("El acta no tiene líneas agregadas.")

    waste_act.status = new_status

    log_action(
        user_id=performed_by_user_id,
        action="CHANGE_WASTE_ACT_STATUS",
        table_name="waste_acts",
        record_id=str(waste_act.id),
        details={
            "previous_status": previous_status,
            "new_status": new_status,
        },
        commit=False,
    )

    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    return waste_act