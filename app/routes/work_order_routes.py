from decimal import Decimal, InvalidOperation

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from app.models.deletion_request import WorkOrderLineDeleteRequest
from app.models.article import Article
from app.models.work_order import WorkOrder
from app.models.mechanic import Mechanic
from app.models.site import Site
from app.models.warehouse import Warehouse
from app.models.user import User
from app.services.work_order_service import (
    WorkOrderServiceError,
    add_work_order_line,
    close_work_order,
    create_work_order,
    finalize_work_order,
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

    responsible_users = (
        User.query
        .filter(User.is_active.is_(True))
        .order_by(User.full_name)
        .all()
    )

    mechanics_query = (
        Mechanic.query
        .filter(Mechanic.is_active.is_(True))
        .order_by(Mechanic.name)
    )
    if active_site_id:
        mechanics_query = mechanics_query.filter(Mechanic.site_id == int(active_site_id))
    mechanics = mechanics_query.all()

    return render_template(
        "work_orders/create.html",
        title="Nueva Orden de Trabajo",
        subtitle="Cree una orden con responsable, predio, bodega y mecánicos asignados.",
        sites=sites,
        warehouses=warehouses,
        responsible_users=responsible_users,
        mechanics=mechanics,
    )

# =========================================================
# CREAR OT
# =========================================================
@work_order_bp.route("/", methods=["POST"])
@login_required
def create_work_order_action():
    try:
        number = (request.form.get("number") or "").strip()
        site_id = request.form.get("site_id")
        warehouse_id = request.form.get("warehouse_id")
        responsible_user_id = request.form.get("responsible_user_id")
        mechanic_ids = request.form.getlist("mechanics")
        description = request.form.get("description")
        equipment_id = request.form.get("equipment_id")
        equipment_code_snapshot = request.form.get("equipment_code_snapshot")

        if not number:
            raise ValueError("El número de la OT es obligatorio.")

        if not site_id:
            raise ValueError("El predio es obligatorio.")

        if not warehouse_id:
            raise ValueError("La bodega es obligatoria.")

        if not responsible_user_id:
            raise ValueError("El responsable es obligatorio.")

        if not mechanic_ids:
            raise ValueError("Debe seleccionar al menos un mecánico.")

        work_order = create_work_order(
            number=number,
            site_id=int(site_id),
            warehouse_id=int(warehouse_id),
            responsible_user_id=int(responsible_user_id),
            created_by_user_id=current_user.id,
            mechanic_ids=[int(m) for m in mechanic_ids],
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
        work_order = WorkOrder.query.get(work_order_id)

        if not work_order:
            raise ValueError("Orden de trabajo no encontrada.")

        available_articles = (
            Article.query
            .filter(Article.is_active.is_(True))
            .order_by(Article.code.asc(), Article.name.asc())
            .all()
        )

        return render_template(
            "work_orders/detail.html",
            title="Detalle de Orden de Trabajo",
            subtitle="Consulte la información general, líneas y acciones de la OT.",
            work_order=work_order,
            available_articles=available_articles,
        )

    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("work_orders.list_work_orders"))

    except Exception:
        flash("Error al cargar la orden de trabajo.", "danger")
        return redirect(url_for("work_orders.list_work_orders"))


# =========================================================
# AGREGAR LÍNEA A OT
# =========================================================
@work_order_bp.route("/<int:work_order_id>/lines", methods=["POST"])
@login_required
def add_line_to_work_order(work_order_id: int):
    try:
        article_id_raw = request.form.get("article_id")
        quantity_raw = (request.form.get("quantity") or "").strip()
        notes = request.form.get("notes")

        if not article_id_raw:
            raise ValueError("Debe seleccionar un artículo.")

        if not quantity_raw:
            raise ValueError("Debe indicar una cantidad.")

        try:
            quantity = Decimal(quantity_raw)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("La cantidad ingresada no es válida.") from exc

        add_work_order_line(
            work_order_id=work_order_id,
            article_id=int(article_id_raw),
            quantity=quantity,
            delivered_by_user_id=current_user.id,
            received_by_user_id=None,
            notes=notes,
            commit=True,
        )

        flash("Línea agregada correctamente a la OT.", "success")

    except (WorkOrderServiceError, ValueError) as exc:
        flash(str(exc), "danger")

    except Exception:
        flash("Error interno al agregar la línea a la OT.", "danger")

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
            has_loaned_tools=False,
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