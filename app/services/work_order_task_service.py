from datetime import datetime, UTC

from app.extensions import db
from app.models.mechanic import Mechanic
from app.models.mechanic_specialty_assignment import MechanicSpecialtyAssignment
from app.models.repair_type import RepairType
from app.models.repair_type_specialty import RepairTypeSpecialty
from app.models.work_order import WorkOrder
from app.models.work_order_task_line import WorkOrderTaskLine
from app.models.work_order_task_line_assignment import WorkOrderTaskLineAssignment


class WorkOrderTaskServiceError(Exception):
    pass


def create_task_line(
    *,
    work_order_id: int,
    repair_type_id: int,
    title: str,
    description: str | None,
    assigned_mechanic_id: int | None,
    created_by_user_id: int,
    commit: bool = True,
):
    work_order = db.session.get(WorkOrder, work_order_id)
    if not work_order:
        raise WorkOrderTaskServiceError("La OT no existe.")

    if work_order.status != "EN_PROCESO":
        raise WorkOrderTaskServiceError("Solo se pueden agregar trabajos a una OT en proceso.")

    repair_type = (
        RepairType.query
        .filter(
            RepairType.id == repair_type_id,
            RepairType.is_active.is_(True),
        )
        .first()
    )
    if not repair_type:
        raise WorkOrderTaskServiceError("El tipo de reparación no existe o está inactivo.")

    if not title or not title.strip():
        raise WorkOrderTaskServiceError("El título es obligatorio.")

    task_line = WorkOrderTaskLine(
        work_order_id=work_order.id,
        repair_type_id=repair_type.id,
        title=title.strip(),
        description=(description or "").strip() or None,
        status="PENDIENTE",
        assigned_mechanic_id=None,
        created_by_user_id=created_by_user_id,
    )

    db.session.add(task_line)
    db.session.flush()

    if assigned_mechanic_id:
        assign_mechanic_to_task_line(
            task_line_id=task_line.id,
            mechanic_id=assigned_mechanic_id,
            commit=False,
        )

    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    return task_line


def assign_mechanic_to_task_line(
    *,
    task_line_id: int,
    mechanic_id: int,
    commit: bool = True,
):
    task_line = db.session.get(WorkOrderTaskLine, task_line_id)
    if not task_line:
        raise WorkOrderTaskServiceError("La línea de trabajo no existe.")

    if task_line.status in {"FINALIZADA", "CANCELADA"}:
        raise WorkOrderTaskServiceError("No se puede reasignar una línea finalizada o cancelada.")

    if not task_line.repair_type_id:
        raise WorkOrderTaskServiceError("La línea no tiene un tipo de reparación asignado.")

    mechanic = db.session.get(Mechanic, mechanic_id)
    if not mechanic:
        raise WorkOrderTaskServiceError("El mecánico no existe.")

    if not mechanic.is_active:
        raise WorkOrderTaskServiceError("El mecánico está inactivo.")

    if task_line.work_order and mechanic.site_id != task_line.work_order.site_id:
        raise WorkOrderTaskServiceError("El mecánico no pertenece al predio de la OT.")

    allowed_specialty_ids = {
        row.specialty_id
        for row in RepairTypeSpecialty.query.filter_by(
            repair_type_id=task_line.repair_type_id
        ).all()
    }

    if not allowed_specialty_ids:
        raise WorkOrderTaskServiceError(
            "El tipo de reparación no tiene especialidades configuradas."
        )

    has_valid_specialty = (
        MechanicSpecialtyAssignment.query
        .filter(
            MechanicSpecialtyAssignment.mechanic_id == mechanic.id,
            MechanicSpecialtyAssignment.specialty_id.in_(allowed_specialty_ids),
        )
        .first()
    )

    if not has_valid_specialty:
        raise WorkOrderTaskServiceError(
            "El mecánico no tiene una especialidad compatible con el tipo de reparación."
        )

    current_assignment = (
        WorkOrderTaskLineAssignment.query
        .filter_by(task_line_id=task_line.id, ended_at=None)
        .first()
    )

    now = datetime.now(UTC)

    if current_assignment:
        current_assignment.ended_at = now
        current_assignment.ended_reason = "REASIGNADO"

        if current_assignment.started_at:
            seconds = int((now - current_assignment.started_at).total_seconds())
            current_assignment.seconds_worked = max(seconds, 0)
            task_line.effective_seconds = (task_line.effective_seconds or 0) + max(seconds, 0)

    new_assignment = WorkOrderTaskLineAssignment(
        task_line_id=task_line.id,
        mechanic_id=mechanic.id,
        started_at=now,
    )

    db.session.add(new_assignment)

    task_line.assigned_mechanic_id = mechanic.id
    task_line.status = "EN_PROCESO"
    task_line.paused_at = None

    if not task_line.started_at:
        task_line.started_at = now

    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    return task_line