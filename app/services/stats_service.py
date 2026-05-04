from sqlalchemy import func
from app.extensions import db
from app.models.work_order_task_line_assignment import WorkOrderTaskLineAssignment
from app.models.work_order_task_line import WorkOrderTaskLine
from app.models.mechanic import Mechanic
from app.models.repair_type import RepairType
from app.models.work_order import WorkOrder


def get_mechanics_stats(site_id=None):
    query = (
        db.session.query(
            Mechanic.id,
            Mechanic.name,
            func.sum(WorkOrderTaskLineAssignment.seconds_worked).label("total_seconds"),
            func.count(WorkOrderTaskLineAssignment.id).label("total_jobs"),
        )
        .join(
            WorkOrderTaskLine,
            WorkOrderTaskLine.id == WorkOrderTaskLineAssignment.task_line_id
        )
        .join(Mechanic, Mechanic.id == WorkOrderTaskLineAssignment.mechanic_id)
        .join(WorkOrder, WorkOrder.id == WorkOrderTaskLine.work_order_id)
    )

    if site_id:
        query = query.filter(WorkOrder.site_id == site_id)

    query = query.group_by(Mechanic.id)

    results = query.all()

    data = []

    for r in results:
        avg = (r.total_seconds / r.total_jobs) if r.total_jobs else 0

        data.append({
            "mechanic_id": r.id,
            "name": r.name,
            "total_seconds": r.total_seconds or 0,
            "total_jobs": r.total_jobs or 0,
            "avg_seconds": avg,
        })

    return data