from sqlalchemy import func, distinct

from app.extensions import db
from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLine
from app.models.work_order_task_line import WorkOrderTaskLine
from app.models.repair_type import RepairType
from app.models.site import Site
from app.models.inventory import WarehouseStock


REPAIR_STATUSES = ["FINALIZADA", "CERRADA"]


def _apply_work_order_filters(query, site_id=None, date_from=None, date_to=None):
    if site_id:
        query = query.filter(WorkOrder.site_id == site_id)

    if date_from:
        query = query.filter(WorkOrder.created_at >= date_from)

    if date_to:
        query = query.filter(WorkOrder.created_at <= date_to)

    return query


def get_equipment_cost_stats(site_id=None, date_from=None, date_to=None, limit=10):
    """
    Costo por equipo según artículos agregados a las OT.

    Fórmula:
    work_order_lines.quantity * warehouse_stock.last_unit_cost

    Solo cuenta líneas:
    - ACTIVE
    - inventory_posted = true
    """

    query = (
        db.session.query(
            WorkOrder.equipment_id.label("equipment_id"),
            WorkOrder.equipment_code_snapshot.label("equipment"),
            func.count(distinct(WorkOrder.id)).label("total_work_orders"),
            func.count(WorkOrderLine.id).label("total_lines"),
            func.coalesce(
                func.sum(
                    WorkOrderLine.quantity
                    * func.coalesce(WarehouseStock.last_unit_cost, 0)
                ),
                0,
            ).label("total_cost"),
        )
        .join(
            WorkOrderLine,
            WorkOrderLine.work_order_id == WorkOrder.id,
        )
        .outerjoin(
            WarehouseStock,
            (WarehouseStock.article_id == WorkOrderLine.article_id)
            & (WarehouseStock.warehouse_id == WorkOrder.warehouse_id),
        )
        .filter(WorkOrder.equipment_id.isnot(None))
        .filter(WorkOrder.status.in_(REPAIR_STATUSES))
        .filter(WorkOrderLine.line_status == "ACTIVE")
        .filter(WorkOrderLine.inventory_posted.is_(True))
    )

    query = _apply_work_order_filters(
        query,
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
    )

    query = (
        query
        .group_by(
            WorkOrder.equipment_id,
            WorkOrder.equipment_code_snapshot,
        )
        .order_by(func.coalesce(func.sum(WorkOrderLine.quantity * func.coalesce(WarehouseStock.last_unit_cost, 0)), 0).desc())
        .limit(limit)
    )

    rows = query.all()

    data = []

    for row in rows:
        total_cost = float(row.total_cost or 0)
        total_work_orders = int(row.total_work_orders or 0)

        data.append(
            {
                "equipment_id": row.equipment_id,
                "equipment": row.equipment or "Sin equipo",
                "total_work_orders": total_work_orders,
                "total_lines": int(row.total_lines or 0),
                "total_cost": total_cost,
                "avg_cost_per_work_order": (
                    total_cost / total_work_orders if total_work_orders else 0
                ),
            }
        )

    return data


def get_most_repaired_equipment(site_id=None, date_from=None, date_to=None, limit=10):
    """
    Equipos más reparados.

    Cuenta OTs FINALIZADAS/CERRADAS por equipo.
    """

    query = (
        db.session.query(
            WorkOrder.equipment_id.label("equipment_id"),
            WorkOrder.equipment_code_snapshot.label("equipment"),
            func.count(distinct(WorkOrder.id)).label("total_repairs"),
        )
        .filter(WorkOrder.equipment_id.isnot(None))
        .filter(WorkOrder.status.in_(REPAIR_STATUSES))
    )

    query = _apply_work_order_filters(
        query,
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
    )

    rows = (
        query
        .group_by(
            WorkOrder.equipment_id,
            WorkOrder.equipment_code_snapshot,
        )
        .order_by(func.count(distinct(WorkOrder.id)).desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "equipment_id": row.equipment_id,
            "equipment": row.equipment or "Sin equipo",
            "total_repairs": int(row.total_repairs or 0),
        }
        for row in rows
    ]


def get_most_entered_equipment(site_id=None, date_from=None, date_to=None, limit=10):
    """
    Equipos más ingresados a taller.

    Cuenta TODAS las OT creadas por equipo, aunque estén EN_PROCESO.
    """

    query = (
        db.session.query(
            WorkOrder.equipment_id.label("equipment_id"),
            WorkOrder.equipment_code_snapshot.label("equipment"),
            func.count(WorkOrder.id).label("total_entries"),
        )
        .filter(WorkOrder.equipment_id.isnot(None))
    )

    query = _apply_work_order_filters(
        query,
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
    )

    rows = (
        query
        .group_by(
            WorkOrder.equipment_id,
            WorkOrder.equipment_code_snapshot,
        )
        .order_by(func.count(WorkOrder.id).desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "equipment_id": row.equipment_id,
            "equipment": row.equipment or "Sin equipo",
            "total_entries": int(row.total_entries or 0),
        }
        for row in rows
    ]


def get_equipment_by_site_stats(date_from=None, date_to=None):
    """
    Comparativa gráfica de equipos reparados por predio.

    Cuenta OTs FINALIZADAS/CERRADAS.
    """

    query = (
        db.session.query(
            Site.id.label("site_id"),
            Site.name.label("site_name"),
            func.count(distinct(WorkOrder.id)).label("total_repairs"),
        )
        .join(WorkOrder, WorkOrder.site_id == Site.id)
        .filter(WorkOrder.equipment_id.isnot(None))
        .filter(WorkOrder.status.in_(REPAIR_STATUSES))
    )

    if date_from:
        query = query.filter(WorkOrder.created_at >= date_from)

    if date_to:
        query = query.filter(WorkOrder.created_at <= date_to)

    rows = (
        query
        .group_by(Site.id, Site.name)
        .order_by(Site.name.asc())
        .all()
    )

    return [
        {
            "site_id": row.site_id,
            "site_name": row.site_name,
            "total_repairs": int(row.total_repairs or 0),
        }
        for row in rows
    ]


def get_equipment_repair_type_stats(site_id=None, date_from=None, date_to=None, limit=10):
    """
    Tipos de reparación más dados en equipos.

    Cuenta trabajos de OT por tipo de reparación.
    """

    query = (
        db.session.query(
            RepairType.id.label("repair_type_id"),
            RepairType.name.label("repair_type_name"),
            func.count(WorkOrderTaskLine.id).label("total_jobs"),
        )
        .join(
            WorkOrderTaskLine,
            WorkOrderTaskLine.repair_type_id == RepairType.id,
        )
        .join(
            WorkOrder,
            WorkOrder.id == WorkOrderTaskLine.work_order_id,
        )
        .filter(WorkOrder.equipment_id.isnot(None))
        .filter(WorkOrder.status.in_(REPAIR_STATUSES))
    )

    query = _apply_work_order_filters(
        query,
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
    )

    rows = (
        query
        .group_by(
            RepairType.id,
            RepairType.name,
        )
        .order_by(func.count(WorkOrderTaskLine.id).desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "repair_type_id": row.repair_type_id,
            "repair_type_name": row.repair_type_name,
            "total_jobs": int(row.total_jobs or 0),
        }
        for row in rows
    ]


def get_equipment_summary(site_id=None, date_from=None, date_to=None):
    """
    KPIs generales de equipos.
    """

    base_query = (
        db.session.query(WorkOrder)
        .filter(WorkOrder.equipment_id.isnot(None))
    )

    base_query = _apply_work_order_filters(
        base_query,
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
    )

    total_entries = base_query.count()

    total_repaired = (
        base_query
        .filter(WorkOrder.status.in_(REPAIR_STATUSES))
        .count()
    )

    total_equipment = (
        db.session.query(func.count(distinct(WorkOrder.equipment_id)))
        .filter(WorkOrder.equipment_id.isnot(None))
    )

    total_equipment = _apply_work_order_filters(
        total_equipment,
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
    ).scalar() or 0

    cost_rows = get_equipment_cost_stats(
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
        limit=100000,
    )

    total_cost = sum(item["total_cost"] for item in cost_rows)

    return {
        "total_entries": int(total_entries or 0),
        "total_repaired": int(total_repaired or 0),
        "total_equipment": int(total_equipment or 0),
        "total_cost": float(total_cost or 0),
    }


def get_equipment_dashboard_data(site_id=None, date_from=None, date_to=None):
    """
    Devuelve todo listo para el dashboard de equipos.
    """

    most_repaired = get_most_repaired_equipment(
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
        limit=10,
    )

    most_entered = get_most_entered_equipment(
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
        limit=10,
    )

    top_cost = get_equipment_cost_stats(
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
        limit=10,
    )

    by_site = get_equipment_by_site_stats(
        date_from=date_from,
        date_to=date_to,
    )

    repair_types = get_equipment_repair_type_stats(
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
        limit=10,
    )

    summary = get_equipment_summary(
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
    )

    return {
        "summary": summary,
        "most_repaired": most_repaired,
        "most_entered": most_entered,
        "top_cost": top_cost,
        "by_site": by_site,
        "repair_types": repair_types,
    }