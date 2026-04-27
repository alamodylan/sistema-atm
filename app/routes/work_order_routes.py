from datetime import UTC, datetime
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models.article import Article
from app.models.deletion_request import WorkOrderLineDeleteRequest
from app.models.equipment import Equipment
from app.models.inventory import WarehouseStock
from app.models.mechanic import Mechanic
from app.models.mechanic_specialty_assignment import MechanicSpecialtyAssignment
from app.models.repair_type import RepairType
from app.models.repair_type_specialty import RepairTypeSpecialty
from app.models.site import Site
from app.models.warehouse import Warehouse
from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLine
from app.models.work_order_task_line import WorkOrderTaskLine
from app.models.work_order_task_line_assignment import WorkOrderTaskLineAssignment
from app.models.work_order_task_line_finish_request import WorkOrderTaskLineFinishRequest
from app.services.work_order_service import (
    WorkOrderServiceError,
    close_work_order,
    create_work_order,
    finalize_work_order,
)
from app.services.work_order_task_service import (
    WorkOrderTaskServiceError,
    create_task_line,
)

work_order_bp = Blueprint("work_orders", __name__)


def _build_repair_type_mechanics_map(site_id: int):
    repair_types = (
        RepairType.query
        .filter(RepairType.is_active.is_(True))
        .order_by(RepairType.name.asc())
        .all()
    )

    repair_type_mechanics_map = {}

    for repair_type in repair_types:
        specialty_ids = [
            assignment.specialty_id
            for assignment in RepairTypeSpecialty.query.filter_by(
                repair_type_id=repair_type.id
            ).all()
        ]

        if not specialty_ids:
            repair_type_mechanics_map[str(repair_type.id)] = []
            continue

        mechanics = (
            Mechanic.query
            .join(
                MechanicSpecialtyAssignment,
                MechanicSpecialtyAssignment.mechanic_id == Mechanic.id,
            )
            .filter(
                Mechanic.site_id == site_id,
                Mechanic.is_active.is_(True),
                MechanicSpecialtyAssignment.specialty_id.in_(specialty_ids),
            )
            .distinct()
            .order_by(Mechanic.name.asc())
            .all()
        )

        repair_type_mechanics_map[str(repair_type.id)] = [
            {
                "id": mechanic.id,
                "name": mechanic.name,
                "code": mechanic.code,
            }
            for mechanic in mechanics
        ]

    return repair_types, repair_type_mechanics_map


# =========================================================
# LISTADO DE ÓRDENES DE TRABAJO
# =========================================================
@work_order_bp.route("/", methods=["GET"])
@login_required
def list_work_orders():
    status = (request.args.get("status") or "").strip()

    try:
        query = WorkOrder.query

        if status:
            query = query.filter(WorkOrder.status == status)

        work_orders = query.order_by(WorkOrder.created_at.desc()).all()

        return render_template(
            "work_orders/index.html",
            title="Órdenes de trabajo",
            subtitle="Consulte órdenes de trabajo por estado.",
            work_orders=work_orders,
            status=status,
        )

    except Exception:
        flash("Error al cargar órdenes de trabajo.", "danger")
        return render_template(
            "work_orders/index.html",
            work_orders=[],
            status=status,
        )


# =========================================================
# PANTALLA CREAR OT
# =========================================================
@work_order_bp.route("/create", methods=["GET"])
@login_required
def create_work_order_page():
    active_site_id = session.get("active_site_id")

    sites = Site.query.filter_by(is_active=True).order_by(Site.name).all()

    warehouses_query = (
        Warehouse.query
        .filter(Warehouse.is_active.is_(True))
        .order_by(Warehouse.name)
    )

    if active_site_id:
        warehouses_query = warehouses_query.filter(Warehouse.site_id == int(active_site_id))

    warehouses = warehouses_query.all()

    equipments = (
        Equipment.query
        .filter(Equipment.is_active.is_(True))
        .order_by(Equipment.code, Equipment.description)
        .all()
    )

    repair_types = []
    repair_type_mechanics_map = {}

    if active_site_id:
        repair_types, repair_type_mechanics_map = _build_repair_type_mechanics_map(
            site_id=int(active_site_id)
        )

    return render_template(
        "work_orders/create.html",
        title="Nueva Orden de Trabajo",
        subtitle="Cree una orden con bodega, equipo, tipo de reparación y mecánico asignado.",
        sites=sites,
        warehouses=warehouses,
        equipments=equipments,
        repair_types=repair_types,
        repair_type_mechanics_map=repair_type_mechanics_map,
    )


# =========================================================
# CREAR OT
# =========================================================
@work_order_bp.route("/", methods=["POST"])
@login_required
def create_work_order_action():
    try:
        site_id = session.get("active_site_id")
        warehouse_id = request.form.get("warehouse_id")
        repair_type_ids = request.form.getlist("repair_type_id[]")
        mechanic_ids = request.form.getlist("mechanic_id[]")
        description = request.form.get("description")
        equipment_id = request.form.get("equipment_id")
        equipment_code_snapshot = request.form.get("equipment_code_snapshot")
        first_repair_type = RepairType.query.get(int(repair_type_ids[0]))
        task_title = first_repair_type.name if first_repair_type else "Trabajo"
        task_description = None

        if not site_id:
            raise ValueError("No hay un predio activo seleccionado.")

        if not warehouse_id:
            raise ValueError("La bodega es obligatoria.")

        if not repair_type_ids:
            raise ValueError("Debe agregar al menos un trabajo.")

        if not mechanic_ids:
            raise ValueError("Debe asignar mecánicos a los trabajos.")

        if not task_title:
            raise ValueError("Debe indicar el trabajo a realizar.")

        work_order = create_work_order(
            number="",
            site_id=int(site_id),
            warehouse_id=int(warehouse_id),
            responsible_user_id=current_user.id,
            created_by_user_id=current_user.id,
            repair_type_id=int(repair_type_ids[0]),
            mechanic_id=int(mechanic_ids[0]),
            task_title=task_title,
            task_description=None,
            description=description,
            equipment_id=int(equipment_id) if equipment_id else None,
            equipment_code_snapshot=equipment_code_snapshot,
            commit=True,
        )

        # Crear trabajos adicionales desde la segunda línea en adelante
        for i in range(1, len(repair_type_ids)):
            rt_id = repair_type_ids[i]
            mech_id = mechanic_ids[i] if i < len(mechanic_ids) else None

            if not rt_id or not mech_id:
                continue

            repair_type = RepairType.query.get(int(rt_id))
            title = repair_type.name if repair_type else "Trabajo"

            create_task_line(
                work_order_id=work_order.id,
                repair_type_id=int(rt_id),
                title=title,
                description=None,
                assigned_mechanic_id=int(mech_id),
                created_by_user_id=current_user.id,
                commit=True,
            )

        flash(f"Orden de trabajo {work_order.number} creada correctamente.", "success")
        return redirect(url_for("work_orders.get_work_order", work_order_id=work_order.id))

    except (WorkOrderServiceError, WorkOrderTaskServiceError, ValueError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("work_orders.create_work_order_page"))

    except Exception as exc:
        print(f"[CREATE OT ERROR] {exc}")
        flash("Error interno al crear la OT.", "danger")
        return redirect(url_for("work_orders.create_work_order_page"))


# =========================================================
# DETALLE OT
# =========================================================
@work_order_bp.route("/<int:work_order_id>", methods=["GET"])
@login_required
def get_work_order(work_order_id: int):
    try:
        source = (request.args.get("source") or "").strip()

        work_order = (
            WorkOrder.query
            .options(
                joinedload(WorkOrder.mechanics),
                joinedload(WorkOrder.equipment),
                joinedload(WorkOrder.warehouse),
                joinedload(WorkOrder.responsible_user),

                selectinload(WorkOrder.requests),
                selectinload(WorkOrder.lines),
                selectinload(WorkOrder.lines).selectinload(WorkOrderLine.article),
                selectinload(WorkOrder.lines).selectinload(WorkOrderLine.delete_requests),
            )
            .filter(WorkOrder.id == work_order_id)
            .first()
        )

        if not work_order:
            raise ValueError("Orden de trabajo no encontrada.")

        # 🔥 CAMBIO CLAVE: precargar request_line_id ya usados en una sola consulta
        existing_request_line_ids = {
            r.request_line_id
            for r in WorkOrderLine.query
                .filter(WorkOrderLine.work_order_id == work_order.id)
                .all()
            if r.request_line_id
        }

        visible_requests = []

        for req in work_order.requests:
            request_lines_for_view = []

            for line in req.lines:
                if line.line_status in ["CANCELADA"]:
                    continue

                if not req.sent_to_warehouse_at:
                    continue

                if hasattr(line, "manager_review_status") and line.manager_review_status != "APROBADA":
                    continue

                # 🔥 AQUÍ ESTABA EL PROBLEMA (ANTES había query por cada línea)
                if line.id in existing_request_line_ids:
                    continue

                if source == "dashboard":
                    stock = (
                        WarehouseStock.query
                        .filter_by(
                            article_id=line.article_id,
                            warehouse_id=work_order.warehouse_id,
                        )
                        .first()
                    )

                    available_qty = (
                        Decimal(str(stock.available_quantity))
                        if stock and stock.available_quantity
                        else Decimal("0")
                    )

                    remaining = Decimal(str(line.quantity_requested)) - Decimal(str(line.quantity_attended))

                    line.stock_available = available_qty
                    line.suggested_attend_quantity = (
                        min(available_qty, remaining)
                        if remaining > 0
                        else Decimal("0")
                    )

                    line.warehouse_action_enabled = available_qty > 0 and remaining > 0
                    line.location_label = stock.location_name if stock and hasattr(stock, "location_name") else "-"

                request_lines_for_view.append(line)

            if not request_lines_for_view:
                continue

            req.filtered_lines = request_lines_for_view
            visible_requests.append(req)

        repair_types, repair_type_mechanics_map = _build_repair_type_mechanics_map(
            site_id=work_order.site_id
        )

        task_lines = (
            WorkOrderTaskLine.query
            .options(
                selectinload(WorkOrderTaskLine.assigned_mechanic),
                selectinload(WorkOrderTaskLine.repair_type),
            )
            .filter(WorkOrderTaskLine.work_order_id == work_order.id)
            .order_by(WorkOrderTaskLine.created_at.asc())
            .all()
        )

        return render_template(
            "work_orders/detail.html",
            title="Detalle de Orden de Trabajo",
            subtitle="Consulte la información general, líneas y acciones de la OT.",
            work_order=work_order,
            available_articles=[],
            visible_requests=visible_requests,
            repair_types=repair_types,
            repair_type_mechanics_map=repair_type_mechanics_map,
            task_lines=task_lines,
            source=source,
        )

    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("work_orders.list_work_orders"))

    except Exception as exc:
        print(f"[ERROR OT DETAIL] {exc}")
        flash("Error al cargar la orden de trabajo.", "danger")
        return redirect(url_for("work_orders.list_work_orders"))


# =========================================================
# CREAR LÍNEA DE TRABAJO EN OT
# =========================================================
@work_order_bp.route("/<int:work_order_id>/tasks", methods=["POST"])
@login_required
def create_task_line_action(work_order_id: int):
    try:
        repair_type_id = request.form.get("repair_type_id")
        mechanic_id = request.form.get("mechanic_id")
        description = request.form.get("description")

        if not repair_type_id:
            raise ValueError("Debe seleccionar un tipo de reparación para el trabajo.")

        repair_type = RepairType.query.get(int(repair_type_id))
        title = repair_type.name if repair_type else "Trabajo"

        create_task_line(
            work_order_id=work_order_id,
            repair_type_id=int(repair_type_id),
            title=title,
            description=description,
            assigned_mechanic_id=int(mechanic_id) if mechanic_id else None,
            created_by_user_id=current_user.id,
            commit=True,
        )

        flash("Línea de trabajo creada correctamente.", "success")

    except (WorkOrderTaskServiceError, ValueError) as exc:
        flash(str(exc), "danger")

    except Exception as exc:
        print(f"[CREATE TASK LINE ERROR] {exc}")
        flash("Error interno al crear la línea de trabajo.", "danger")

    return redirect(url_for("work_orders.get_work_order", work_order_id=work_order_id))


# =========================================================
# BLOQUEADO: AGREGAR LÍNEA DIRECTA
# =========================================================
@work_order_bp.route("/<int:work_order_id>/lines", methods=["POST"])
@login_required
def add_line_to_work_order(work_order_id: int):
    flash("Las líneas deben generarse desde solicitudes (flujo correcto).", "warning")
    return redirect(url_for("work_orders.get_work_order", work_order_id=work_order_id))


# =========================================================
# FINALIZAR OT
# =========================================================
@work_order_bp.route("/<int:work_order_id>/finalize", methods=["POST"])
@login_required
def finalize_work_order_action(work_order_id: int):
    try:
        finalize_work_order(
            work_order_id=work_order_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Orden de trabajo finalizada correctamente.", "success")

    except WorkOrderServiceError as exc:
        flash(str(exc), "danger")

    except Exception as exc:
        print(f"[FINALIZE OT ERROR] {exc}")
        flash("Error interno al finalizar la OT.", "danger")

    return redirect(url_for("work_orders.get_work_order", work_order_id=work_order_id))


# =========================================================
# CERRAR OT
# =========================================================
@work_order_bp.route("/<int:work_order_id>/close", methods=["POST"])
@login_required
def close_work_order_action(work_order_id: int):
    try:
        close_work_order(
            work_order_id=work_order_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Orden de trabajo cerrada correctamente.", "success")

    except WorkOrderServiceError as exc:
        flash(str(exc), "danger")

    except Exception as exc:
        print(f"[CLOSE OT ERROR] {exc}")
        flash("Error interno al cerrar la OT.", "danger")

    return redirect(url_for("work_orders.get_work_order", work_order_id=work_order_id))


# =========================================================
# IMPRESIÓN OT
# =========================================================
@work_order_bp.route("/<int:work_order_id>/print", methods=["GET"])
@login_required
def print_work_order(work_order_id: int):
    try:
        work_order = WorkOrder.query.get(work_order_id)

        if not work_order:
            raise ValueError("Orden de trabajo no encontrada.")

        return render_template(
            "work_orders/print.html",
            work_order=work_order,
        )

    except Exception:
        flash("Error al generar impresión.", "danger")
        return redirect(url_for("work_orders.get_work_order", work_order_id=work_order_id))

@work_order_bp.route("/tasks/<int:task_id>/pause", methods=["POST"])
@login_required
def pause_task_line_action(task_id):
    try:
        task = WorkOrderTaskLine.query.get_or_404(task_id)

        if task.status != "EN_PROCESO":
            flash("Solo se pueden pausar trabajos en proceso.", "warning")
            return redirect(request.referrer or "/")

        now = datetime.now(UTC)

        # cerrar assignment activo
        active_assignment = next(
            (a for a in task.assignments if a.ended_at is None),
            None
        )

        if active_assignment:
            seconds = int((now - active_assignment.started_at).total_seconds())
            active_assignment.ended_at = now
            active_assignment.seconds_worked += seconds
            active_assignment.ended_reason = "PAUSA_JEFATURA"

            task.effective_seconds += seconds

        task.status = "PAUSADA"
        task.paused_at = now

        db.session.commit()
        flash("Trabajo pausado correctamente.", "success")

    except Exception as exc:
        db.session.rollback()
        print(f"[PAUSE TASK ERROR] {exc}")
        flash("Error al pausar el trabajo.", "danger")

    return redirect(request.referrer or "/")

@work_order_bp.route("/tasks/<int:task_id>/resume", methods=["POST"])
@login_required
def resume_task_line_action(task_id):
    try:
        task = WorkOrderTaskLine.query.get_or_404(task_id)

        if task.status != "PAUSADA":
            flash("Solo se pueden reanudar trabajos pausados.", "warning")
            return redirect(request.referrer or "/")

        now = datetime.now(UTC)

        new_assignment = WorkOrderTaskLineAssignment(
            task_line_id=task.id,
            mechanic_id=task.assigned_mechanic_id,
            started_at=now,
        )

        db.session.add(new_assignment)

        task.status = "EN_PROCESO"
        task.paused_at = None

        db.session.commit()
        flash("Trabajo reanudado correctamente.", "success")

    except Exception as exc:
        db.session.rollback()
        print(f"[RESUME TASK ERROR] {exc}")
        flash("Error al reanudar el trabajo.", "danger")

    return redirect(request.referrer or "/")

@work_order_bp.route("/tasks/<int:task_id>/replace-mechanic", methods=["POST"])
@login_required
def replace_task_line_mechanic_action(task_id):
    try:
        new_mechanic_id = request.form.get("mechanic_id")

        if not new_mechanic_id:
            raise ValueError("Debe seleccionar un mecánico.")

        task = WorkOrderTaskLine.query.get_or_404(task_id)

        now = datetime.now(UTC)

        # cerrar assignment actual
        active_assignment = next(
            (a for a in task.assignments if a.ended_at is None),
            None
        )

        if active_assignment:
            seconds = int((now - active_assignment.started_at).total_seconds())
            active_assignment.ended_at = now
            active_assignment.seconds_worked += seconds
            active_assignment.ended_reason = "REASIGNADO"

            task.effective_seconds += seconds

        # asignar nuevo mecánico
        task.assigned_mechanic_id = int(new_mechanic_id)

        new_assignment = WorkOrderTaskLineAssignment(
            task_line_id=task.id,
            mechanic_id=int(new_mechanic_id),
            started_at=now,
        )

        db.session.add(new_assignment)

        task.status = "EN_PROCESO"
        task.paused_at = None

        db.session.commit()
        flash("Mecánico reemplazado correctamente.", "success")

    except Exception as exc:
        db.session.rollback()
        print(f"[REPLACE MECHANIC ERROR] {exc}")
        flash("Error al reemplazar mecánico.", "danger")

    return redirect(request.referrer or "/")

# =========================================================
# LISTADO SOLICITUDES DE ELIMINACIÓN
# =========================================================
@work_order_bp.route("/deletion-requests", methods=["GET"])
@login_required
def deletion_requests_list():
    status = (request.args.get("status") or "").strip()

    try:
        query = WorkOrderLineDeleteRequest.query

        if status:
            query = query.filter(WorkOrderLineDeleteRequest.status == status)

        delete_requests = query.order_by(
            WorkOrderLineDeleteRequest.created_at.desc()
        ).all()

        return render_template(
            "work_orders/deletion_requests.html",
            title="Solicitudes de Eliminación",
            subtitle="Gestione solicitudes de eliminación de líneas de OT.",
            delete_requests=delete_requests,
            status=status,
        )

    except Exception:
        flash("Error al cargar las solicitudes de eliminación.", "danger")
        return render_template(
            "work_orders/deletion_requests.html",
            title="Solicitudes de Eliminación",
            subtitle="Gestione solicitudes de eliminación de líneas de OT.",
            delete_requests=[],
            status=status,
        )


# =========================================================
# APROBAR FINALIZACIÓN DE TRABAJO
# =========================================================
@work_order_bp.route("/tasks/<int:task_id>/approve", methods=["POST"])
@login_required
def approve_task_finish(task_id):
    try:
        task = WorkOrderTaskLine.query.get_or_404(task_id)

        if task.status != "FINALIZACION_SOLICITADA":
            flash("El trabajo no tiene una solicitud de finalización pendiente.", "warning")
            return redirect(url_for("dashboard.manager_dashboard"))

        task.status = "FINALIZADA"
        task.approved_finished_at = datetime.now(UTC)

        finish_request = (
            WorkOrderTaskLineFinishRequest.query
            .filter_by(task_line_id=task.id, status="PENDIENTE")
            .first()
        )

        if finish_request:
            finish_request.status = "APROBADA"
            if hasattr(finish_request, "reviewed_by_user_id"):
                finish_request.reviewed_by_user_id = current_user.id
            if hasattr(finish_request, "reviewed_at"):
                finish_request.reviewed_at = datetime.now(UTC)

        db.session.commit()
        flash("Trabajo aprobado correctamente.", "success")

    except Exception as exc:
        db.session.rollback()
        print(f"[APPROVE TASK FINISH ERROR] {exc}")
        flash("Error al aprobar la finalización del trabajo.", "danger")

    return redirect(url_for("dashboard.manager_dashboard"))


# =========================================================
# RECHAZAR FINALIZACIÓN DE TRABAJO
# =========================================================
@work_order_bp.route("/tasks/<int:task_id>/reject", methods=["POST"])
@login_required
def reject_task_finish(task_id):
    try:
        task = WorkOrderTaskLine.query.get_or_404(task_id)

        if task.status != "FINALIZACION_SOLICITADA":
            flash("El trabajo no tiene una solicitud de finalización pendiente.", "warning")
            return redirect(url_for("dashboard.manager_dashboard"))

        task.status = "EN_PROCESO"
        task.finish_requested_at = None

        now = datetime.now(UTC)

        if task.assigned_mechanic_id:
            new_assignment = WorkOrderTaskLineAssignment(
                task_line_id=task.id,
                mechanic_id=task.assigned_mechanic_id,
                started_at=now,
            )
            db.session.add(new_assignment)

        finish_request = (
            WorkOrderTaskLineFinishRequest.query
            .filter_by(task_line_id=task.id, status="PENDIENTE")
            .first()
        )

        if finish_request:
            finish_request.status = "DESESTIMADA"
            if hasattr(finish_request, "reviewed_by_user_id"):
                finish_request.reviewed_by_user_id = current_user.id
            if hasattr(finish_request, "reviewed_at"):
                finish_request.reviewed_at = now

        db.session.commit()
        flash("Finalización rechazada. El trabajo volvió a estar en proceso.", "success")

    except Exception as exc:
        db.session.rollback()
        print(f"[REJECT TASK FINISH ERROR] {exc}")
        flash("Error al rechazar la finalización del trabajo.", "danger")

    return redirect(url_for("dashboard.manager_dashboard"))