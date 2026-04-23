from datetime import datetime, UTC

from app.extensions import db
from app.models.mechanic import Mechanic
from app.models.work_order import WorkOrder
from app.models.work_order_task_line import WorkOrderTaskLine
from app.models.mechanic_specialty_assignment import MechanicSpecialtyAssignment
from app.models.work_order_task_line_assignment import WorkOrderTaskLineAssignment


class WorkOrderTaskServiceError(Exception):
    pass


def create_task_line(
    *,
    work_order_id: int,
    specialty_id: int,
    title: str,
    description: str | None,
    assigned_mechanic_id: int | None,
    created_by_user_id: int,
    commit: bool = True,
):
    work_order = db.session.get(WorkOrder, work_order_id)
    if not work_order:
        raise WorkOrderTaskServiceError("La OT no existe.")

    if not title:
        raise WorkOrderTaskServiceError("El título es obligatorio.")

    task_line = WorkOrderTaskLine(
        work_order_id=work_order.id,
        specialty_id=specialty_id,
        title=title.strip(),
        description=(description or "").strip() or None,
        status="PENDIENTE",
        assigned_mechanic_id=None,
        created_by_user_id=created_by_user_id,
    )

    db.session.add(task_line)
    db.session.flush()

    # 🔹 Si se manda mecánico, asignarlo de una vez
    if assigned_mechanic_id:
        assign_mechanic_to_task_line(
            task_line_id=task_line.id,
            mechanic_id=assigned_mechanic_id,
            commit=False,
        )

    if commit:
        db.session.commit()

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

    mechanic = db.session.get(Mechanic, mechanic_id)
    if not mechanic:
        raise WorkOrderTaskServiceError("El mecánico no existe.")

    # 🔥 Validar especialidad
    has_specialty = MechanicSpecialtyAssignment.query.filter_by(
        mechanic_id=mechanic_id,
        specialty_id=task_line.specialty_id
    ).first()

    if not has_specialty:
        raise WorkOrderTaskServiceError(
            "El mecánico no tiene la especialidad requerida."
        )

    # 🔹 Cerrar asignación anterior si existe
    current_assignment = (
        WorkOrderTaskLineAssignment.query
        .filter_by(task_line_id=task_line.id, ended_at=None)
        .first()
    )

    if current_assignment:
        current_assignment.ended_at = datetime.now(UTC)
        current_assignment.ended_reason = "REASIGNADO"

    # 🔹 Nueva asignación
    new_assignment = WorkOrderTaskLineAssignment(
        task_line_id=task_line.id,
        mechanic_id=mechanic_id,
        started_at=datetime.now(UTC),
    )

    db.session.add(new_assignment)

    # 🔹 Actualizar línea
    task_line.assigned_mechanic_id = mechanic_id
    task_line.status = "EN_PROCESO"

    if not task_line.started_at:
        task_line.started_at = datetime.now(UTC)

    if commit:
        db.session.commit()

    return task_line