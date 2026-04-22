from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, UTC
from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models.warehouse import Warehouse
from app.models.waste_act import WasteAct
from app.models.waste_act_line import WasteActLine
from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLine
from app.services.audit_service import log_action


class WasteServiceError(Exception):
    pass


def _parse_date(value, field_name: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if isinstance(value, datetime):
        return value.date()

    if not value:
        raise WasteServiceError(f"El campo {field_name} es obligatorio.")

    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError as exc:
        raise WasteServiceError(f"El campo {field_name} no tiene una fecha válida.") from exc


def _build_waste_act_number() -> str:
    numbers = db.session.query(WasteAct.number).all()

    max_value = 0
    for (raw_number,) in numbers:
        if not raw_number:
            continue

        match = re.search(r"(\d+)$", str(raw_number).strip())
        if not match:
            continue

        value = int(match.group(1))
        if value > max_value:
            max_value = value

    next_value = max_value + 1
    return f"{next_value:07d}"


def create_waste_act(
    *,
    site_id: int,
    warehouse_id: int,
    date_from,
    date_to,
    created_by_user_id: int,
    notes: str | None = None,
    commit: bool = True,
) -> WasteAct:
    if not site_id:
        raise WasteServiceError("El predio es obligatorio.")

    if not warehouse_id:
        raise WasteServiceError("La bodega es obligatoria.")

    parsed_date_from = _parse_date(date_from, "date_from")
    parsed_date_to = _parse_date(date_to, "date_to")

    if parsed_date_from > parsed_date_to:
        raise WasteServiceError("La fecha inicial no puede ser mayor que la fecha final.")

    warehouse = db.session.get(Warehouse, warehouse_id)
    if not warehouse:
        raise WasteServiceError("La bodega indicada no existe.")

    if warehouse.site_id != site_id:
        raise WasteServiceError("La bodega no pertenece al predio indicado.")

    number = _build_waste_act_number()

    existing = WasteAct.query.filter_by(number=number).first()
    if existing:
        raise WasteServiceError("No se pudo generar un consecutivo único para el acta.")

    waste_act = WasteAct(
        number=number,
        site_id=site_id,
        warehouse_id=warehouse_id,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
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
    parsed_date_from = _parse_date(date_from, "date_from")
    parsed_date_to = _parse_date(date_to, "date_to")

    if parsed_date_from > parsed_date_to:
        raise WasteServiceError("La fecha inicial no puede ser mayor que la fecha final.")

    start_dt = datetime.combine(parsed_date_from, time.min, tzinfo=UTC)
    end_dt_exclusive = datetime.combine(
        parsed_date_to + timedelta(days=1),
        time.min,
        tzinfo=UTC,
    )

    query = (
        WorkOrderLine.query
        .join(WorkOrder, WorkOrder.id == WorkOrderLine.work_order_id)
        .filter(WorkOrder.status.in_(["FINALIZADA", "CERRADA"]))
        .filter(WorkOrderLine.quantity > 0)
        .filter(WorkOrderLine.inventory_posted.is_(True))
        .filter(WorkOrderLine.line_status == "ACTIVE")
        .filter(WorkOrderLine.delivered_at.isnot(None))
        .filter(WorkOrderLine.delivered_at >= start_dt)
        .filter(WorkOrderLine.delivered_at < end_dt_exclusive)
        .filter(~WorkOrderLine.waste_act_lines.any())
    )

    if site_id:
        query = query.filter(WorkOrder.site_id == site_id)

    if warehouse_id:
        query = query.filter(WorkOrder.warehouse_id == warehouse_id)

    return query.order_by(
        WorkOrderLine.delivered_at.asc(),
        WorkOrderLine.id.asc(),
    ).all()


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
    waste_act = db.session.get(WasteAct, waste_act_id)
    if not waste_act:
        raise WasteServiceError("El acta de desecho no existe.")

    if waste_act.status not in {"BORRADOR", "REGISTRADA"}:
        raise WasteServiceError(
            "Solo se pueden agregar líneas a un acta en estado BORRADOR o REGISTRADA."
        )

    line = db.session.get(WorkOrderLine, work_order_line_id)
    if not line:
        raise WasteServiceError("La línea de OT no existe.")

    if line.line_status != "ACTIVE":
        raise WasteServiceError("Solo se pueden usar líneas activas.")

    if not line.inventory_posted:
        raise WasteServiceError("La línea no impactó inventario, no aplica para desecho.")

    if line.delivered_at is None:
        raise WasteServiceError("La línea no tiene fecha de entrega registrada.")

    if line.work_order is None:
        raise WasteServiceError("La línea no tiene una OT asociada válida.")

    if line.work_order.status not in {"FINALIZADA", "CERRADA"}:
        raise WasteServiceError(
            "Solo se pueden usar líneas de OTs finalizadas o cerradas."
        )

    if line.work_order.site_id != waste_act.site_id:
        raise WasteServiceError("La línea no pertenece al mismo predio del acta de desecho.")

    if line.work_order.warehouse_id != waste_act.warehouse_id:
        raise WasteServiceError("La línea no pertenece a la misma bodega del acta de desecho.")

    line_delivered_date = line.delivered_at.date()
    if line_delivered_date < waste_act.date_from or line_delivered_date > waste_act.date_to:
        raise WasteServiceError("La línea no está dentro del rango de fechas del acta.")

    existing_any = WasteActLine.query.filter_by(work_order_line_id=work_order_line_id).first()
    if existing_any:
        raise WasteServiceError("La línea ya fue agregada a un acta de desecho.")

    try:
        qty = Decimal(str(quantity))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise WasteServiceError("La cantidad indicada no es válida.") from exc

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

    if waste_act.status == "BORRADOR":
        waste_act.status = "REGISTRADA"

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
            "waste_act_status": waste_act.status,
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


def set_signed_pdf_path(
    *,
    waste_act_id: int,
    signed_pdf_path: str,
    performed_by_user_id: int,
    commit: bool = True,
) -> WasteAct:
    waste_act = db.session.get(WasteAct, waste_act_id)
    if not waste_act:
        raise WasteServiceError("El acta de desecho no existe.")

    if waste_act.status not in {"REGISTRADA", "IMPRESA"}:
        raise WasteServiceError(
            "Solo se puede adjuntar PDF a un acta en estado REGISTRADA o IMPRESA."
        )

    if not signed_pdf_path or not str(signed_pdf_path).strip():
        raise WasteServiceError("La ruta del PDF firmado es obligatoria.")

    waste_act.signed_pdf_path = str(signed_pdf_path).strip()

    log_action(
        user_id=performed_by_user_id,
        action="UPLOAD_WASTE_ACT_SIGNED_PDF",
        table_name="waste_acts",
        record_id=str(waste_act.id),
        details={
            "signed_pdf_path": waste_act.signed_pdf_path,
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

    if not new_status:
        raise WasteServiceError("El estado solicitado no es válido.")

    normalized_status = str(new_status).strip().upper()

    if normalized_status not in allowed_statuses:
        raise WasteServiceError("El estado solicitado no es válido.")

    waste_act = db.session.get(WasteAct, waste_act_id)
    if not waste_act:
        raise WasteServiceError("El acta de desecho no existe.")

    previous_status = waste_act.status

    if previous_status == normalized_status:
        return waste_act

    if normalized_status not in transitions.get(previous_status, set()):
        raise WasteServiceError(
            f"No se puede cambiar el acta de {previous_status} a {normalized_status}."
        )

    if normalized_status in {"REGISTRADA", "IMPRESA", "CERRADA"} and waste_act.lines.count() == 0:
        raise WasteServiceError("El acta no tiene líneas agregadas.")

    if normalized_status == "CERRADA" and not waste_act.signed_pdf_path:
        raise WasteServiceError(
            "Para cerrar el acta debe subir el PDF firmado."
        )

    if normalized_status == "CANCELADA":
        if previous_status not in {"BORRADOR", "REGISTRADA"}:
            raise WasteServiceError(
                "Solo se pueden anular actas en estado BORRADOR o REGISTRADA."
            )

        deleted_count = WasteActLine.query.filter_by(
            waste_act_id=waste_act.id
        ).delete(synchronize_session=False)

        log_action(
            user_id=performed_by_user_id,
            action="CANCEL_WASTE_ACT_RELEASE_LINES",
            table_name="waste_act_lines",
            record_id=str(waste_act.id),
            details={
                "released_lines_count": deleted_count,
            },
            commit=False,
        )

    waste_act.status = normalized_status

    log_action(
        user_id=performed_by_user_id,
        action="CHANGE_WASTE_ACT_STATUS",
        table_name="waste_acts",
        record_id=str(waste_act.id),
        details={
            "previous_status": previous_status,
            "new_status": normalized_status,
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