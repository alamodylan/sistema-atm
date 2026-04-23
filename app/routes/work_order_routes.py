from decimal import Decimal, InvalidOperation

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models.article import Article
from app.models.deletion_request import WorkOrderLineDeleteRequest
from app.models.equipment import Equipment
from app.models.mechanic import Mechanic
from app.models.mechanic_specialty import MechanicSpecialty
from app.models.service_catalog import ServiceCatalog
from app.models.site import Site
from app.models.warehouse import Warehouse
from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLine
from app.models.work_order_task_line import WorkOrderTaskLine
from app.models.inventory import WarehouseStock
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

    mechanics_query = (
        Mechanic.query
        .filter(Mechanic.is_active.is_(True))
        .order_by(Mechanic.name)
    )
    if active_site_id:
        mechanics_query = mechanics_query.filter(Mechanic.site_id == int(active_site_id))
    mechanics = mechanics_query.all()

    equipments = (
        Equipment.query
        .filter(Equipment.is_active.is_(True))
        .order_by(Equipment.code, Equipment.description)
        .all()
    )

    services = (
        ServiceCatalog.query
        .filter(ServiceCatalog.is_active.is_(True))
        .order_by(ServiceCatalog.name, ServiceCatalog.code)
        .all()
    )

    return render_template(
        "work_orders/create.html",
        title="Nueva Orden de Trabajo",
        subtitle="Cree una orden con responsable, bodega, equipo y mecánicos asignados.",
        sites=sites,
        warehouses=warehouses,
        mechanics=mechanics,
        equipments=equipments,
        services=services,
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
        responsible_user_id = current_user.id
        mechanic_ids = request.form.getlist("mechanics")
        service_id = request.form.get("service_id")
        service_notes = request.form.get("service_notes")
        description = request.form.get("description")
        equipment_id = request.form.get("equipment_id")
        equipment_code_snapshot = request.form.get("equipment_code_snapshot")

        if not site_id:
            raise ValueError("No hay un predio activo seleccionado.")

        if not warehouse_id:
            raise ValueError("La bodega es obligatoria.")

        if not mechanic_ids:
            raise ValueError("Debe seleccionar al menos un mecánico.")

        if not service_id:
            raise ValueError("Debe seleccionar un tipo de reparación.")

        work_order = create_work_order(
            number="",
            site_id=int(site_id),
            warehouse_id=int(warehouse_id),
            responsible_user_id=int(responsible_user_id),
            created_by_user_id=current_user.id,
            mechanic_ids=[int(m) for m in mechanic_ids],
            service_id=int(service_id),
            service_notes=service_notes,
            description=description,
            equipment_id=int(equipment_id) if equipment_id else None,
            equipment_code_snapshot=equipment_code_snapshot,
            commit=True,
        )

        flash(f"Orden de trabajo {work_order.number} creada correctamente.", "success")
        return redirect(url_for("work_orders.get_work_order", work_order_id=work_order.id))

    except (WorkOrderServiceError, ValueError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("work_orders.create_work_order_page"))

    except Exception:
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
            )
            .filter(WorkOrder.id == work_order_id)
            .first()
        )

        if not work_order:
            raise ValueError("Orden de trabajo no encontrada.")

        available_articles = (
            Article.query
            .filter(Article.is_active.is_(True))
            .order_by(Article.code.asc(), Article.name.asc())
            .all()
        )

        visible_requests = []

        for req in work_order.requests:
            request_lines_for_view = []

            for line in req.lines:
                existing_ot_line = (
                    WorkOrderLine.query
                    .filter_by(request_line_id=line.id)
                    .first()
                )

                if existing_ot_line:
                    continue

                if source == "dashboard":
                    if not req.sent_to_warehouse_at:
                        continue

                    if line.manager_review_status != "APROBADA":
                        continue

                    stock = (
                        WarehouseStock.query
                        .filter_by(
                            article_id=line.article_id,
                            warehouse_id=work_order.warehouse_id
                        )
                        .first()
                    )

                    available_qty = Decimal(str(stock.available_quantity)) if stock and stock.available_quantity else Decimal("0")
                    remaining = Decimal(str(line.quantity_requested)) - Decimal(str(line.quantity_attended))

                    line.stock_available = available_qty
                    line.suggested_attend_quantity = min(available_qty, remaining) if remaining > 0 else Decimal("0")
                    line.warehouse_action_enabled = available_qty > 0 and remaining > 0
                    line.location_label = stock.location_name if stock and hasattr(stock, "location_name") else "-"

                request_lines_for_view.append(line)

            if not request_lines_for_view:
                continue

            req.filtered_lines = request_lines_for_view
            visible_requests.append(req)

        available_mechanics = []
        if work_order.status == "EN_PROCESO":
            assigned_ids = {mechanic.id for mechanic in work_order.mechanics}
            available_mechanics = (
                Mechanic.query
                .filter(
                    Mechanic.is_active.is_(True),
                    Mechanic.site_id == work_order.site_id,
                    ~Mechanic.id.in_(assigned_ids) if assigned_ids else True,
                )
                .order_by(Mechanic.name.asc())
                .all()
            )

        specialties = (
            MechanicSpecialty.query
            .filter(MechanicSpecialty.is_active.is_(True))
            .order_by(MechanicSpecialty.name.asc())
            .all()
        )

        task_lines = (
            WorkOrderTaskLine.query
            .options(
                selectinload(WorkOrderTaskLine.assigned_mechanic),
                selectinload(WorkOrderTaskLine.specialty),
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
            available_articles=available_articles,
            visible_requests=visible_requests,
            available_mechanics=available_mechanics,
            specialties=specialties,
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
        title = (request.form.get("title") or "").strip()
        specialty_id = request.form.get("specialty_id")
        mechanic_id = request.form.get("mechanic_id")
        description = request.form.get("description")

        if not title:
            raise ValueError("El título del trabajo es obligatorio.")

        if not specialty_id:
            raise ValueError("Debe seleccionar una especialidad.")

        create_task_line(
            work_order_id=work_order_id,
            specialty_id=int(specialty_id),
            title=title,
            description=description,
            assigned_mechanic_id=int(mechanic_id) if mechanic_id else None,
            created_by_user_id=current_user.id,
            commit=True,
        )

        flash("Línea de trabajo creada correctamente.", "success")

    except (WorkOrderTaskServiceError, ValueError) as exc:
        flash(str(exc), "danger")

    except Exception:
        flash("Error interno al crear la línea de trabajo.", "danger")

    return redirect(url_for("work_orders.get_work_order", work_order_id=work_order_id))


# =========================================================
# AGREGAR MECÁNICO A OT
# =========================================================
@work_order_bp.route("/<int:work_order_id>/mechanics/add", methods=["POST"])
@login_required
def add_mechanic_to_work_order_action(work_order_id: int):
    try:
        mechanic_id = request.form.get("mechanic_id")

        if not mechanic_id:
            raise ValueError("Debe seleccionar un mecánico.")

        work_order = (
            WorkOrder.query
            .options(joinedload(WorkOrder.mechanics))
            .filter(WorkOrder.id == work_order_id)
            .first()
        )

        if not work_order:
            raise ValueError("Orden de trabajo no encontrada.")

        if work_order.status != "EN_PROCESO":
            raise ValueError("Solo se pueden agregar mecánicos a OTs en proceso.")

        mechanic = (
            Mechanic.query
            .filter(
                Mechanic.id == int(mechanic_id),
                Mechanic.site_id == work_order.site_id,
                Mechanic.is_active.is_(True),
            )
            .first()
        )

        if not mechanic:
            raise ValueError("El mecánico no existe o no pertenece al predio de la OT.")

        if any(existing.id == mechanic.id for existing in work_order.mechanics):
            raise ValueError("Ese mecánico ya está asignado a la OT.")

        work_order.mechanics.append(mechanic)
        db.session.commit()

        flash("Mecánico agregado correctamente a la OT.", "success")

    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")

    except Exception:
        db.session.rollback()
        flash("Error interno al agregar el mecánico a la OT.", "danger")

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

    except Exception:
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

    except Exception:
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