from sqlalchemy import func

from app.extensions import db
from app.models.work_order_task_line_assignment import WorkOrderTaskLineAssignment
from app.models.work_order_task_line import WorkOrderTaskLine
from app.models.mechanic import Mechanic
from app.models.repair_type import RepairType
from app.models.work_order import WorkOrder


def _apply_common_filters(query, site_id=None, mechanic_id=None, repair_type_id=None, date_from=None, date_to=None):
    if site_id:
        query = query.filter(WorkOrder.site_id == site_id)

    if mechanic_id:
        query = query.filter(Mechanic.id == mechanic_id)

    if repair_type_id:
        query = query.filter(WorkOrderTaskLine.repair_type_id == repair_type_id)

    if date_from:
        query = query.filter(WorkOrderTaskLineAssignment.started_at >= date_from)

    if date_to:
        query = query.filter(WorkOrderTaskLineAssignment.started_at <= date_to)

    return query


def get_mechanics_stats(site_id=None, mechanic_id=None, repair_type_id=None, date_from=None, date_to=None):
    query = (
        db.session.query(
            Mechanic.id,
            Mechanic.name,
            Mechanic.site_id,
            func.sum(WorkOrderTaskLineAssignment.seconds_worked).label("total_seconds"),
            func.count(WorkOrderTaskLineAssignment.id).label("total_jobs"),
            func.count(func.distinct(WorkOrderTaskLine.work_order_id)).label("total_work_orders"),
        )
        .join(
            WorkOrderTaskLine,
            WorkOrderTaskLine.id == WorkOrderTaskLineAssignment.task_line_id,
        )
        .join(Mechanic, Mechanic.id == WorkOrderTaskLineAssignment.mechanic_id)
        .join(WorkOrder, WorkOrder.id == WorkOrderTaskLine.work_order_id)
        .filter(WorkOrderTaskLineAssignment.seconds_worked.isnot(None))
        .filter(WorkOrderTaskLineAssignment.seconds_worked > 0)
    )

    query = _apply_common_filters(
        query,
        site_id=site_id,
        mechanic_id=mechanic_id,
        repair_type_id=repair_type_id,
        date_from=date_from,
        date_to=date_to,
    )

    query = query.group_by(
        Mechanic.id,
        Mechanic.name,
        Mechanic.site_id,
    )

    results = query.all()

    data = []

    for r in results:
        total_seconds = int(r.total_seconds or 0)
        total_jobs = int(r.total_jobs or 0)
        avg_seconds = (total_seconds / total_jobs) if total_jobs else 0

        data.append(
            {
                "mechanic_id": r.id,
                "name": r.name,
                "site_id": r.site_id,
                "total_seconds": total_seconds,
                "total_jobs": total_jobs,
                "total_work_orders": int(r.total_work_orders or 0),
                "avg_seconds": avg_seconds,
            }
        )

    return data


def get_repair_type_stats(site_id=None, mechanic_id=None, repair_type_id=None, date_from=None, date_to=None):
    query = (
        db.session.query(
            RepairType.id,
            RepairType.name,
            func.sum(WorkOrderTaskLineAssignment.seconds_worked).label("total_seconds"),
            func.count(WorkOrderTaskLineAssignment.id).label("total_jobs"),
            func.count(func.distinct(WorkOrderTaskLine.work_order_id)).label("total_work_orders"),
        )
        .join(WorkOrderTaskLine, WorkOrderTaskLine.repair_type_id == RepairType.id)
        .join(
            WorkOrderTaskLineAssignment,
            WorkOrderTaskLineAssignment.task_line_id == WorkOrderTaskLine.id,
        )
        .join(Mechanic, Mechanic.id == WorkOrderTaskLineAssignment.mechanic_id)
        .join(WorkOrder, WorkOrder.id == WorkOrderTaskLine.work_order_id)
        .filter(WorkOrderTaskLineAssignment.seconds_worked.isnot(None))
        .filter(WorkOrderTaskLineAssignment.seconds_worked > 0)
    )

    query = _apply_common_filters(
        query,
        site_id=site_id,
        mechanic_id=mechanic_id,
        repair_type_id=repair_type_id,
        date_from=date_from,
        date_to=date_to,
    )

    query = query.group_by(
        RepairType.id,
        RepairType.name,
    )

    results = query.all()

    data = []

    for r in results:
        total_seconds = int(r.total_seconds or 0)
        total_jobs = int(r.total_jobs or 0)
        avg_seconds = (total_seconds / total_jobs) if total_jobs else 0

        data.append(
            {
                "repair_type_id": r.id,
                "repair_type_name": r.name,
                "total_seconds": total_seconds,
                "total_jobs": int(r.total_jobs or 0),
                "total_work_orders": int(r.total_work_orders or 0),
                "avg_seconds": avg_seconds,
            }
        )

    return data


def get_mechanics_for_filter(site_id=None):
    query = Mechanic.query.filter(Mechanic.is_active.is_(True))

    if site_id:
        query = query.filter(Mechanic.site_id == site_id)

    return query.order_by(Mechanic.name.asc()).all()


def get_repair_types_for_filter():
    return (
        RepairType.query
        .filter(RepairType.is_active.is_(True))
        .order_by(RepairType.name.asc())
        .all()
    )