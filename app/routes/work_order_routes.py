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
from app.models.work_order_request import WorkOrderRequest
from app.models.work_order_request_line import WorkOrderRequestLine
from app.models.work_order_task_line_finish_request import WorkOrderTaskLineFinishRequest
from app.utils.permissions import permission_required
import re
from flask import jsonify
from app.models.equipment_type import EquipmentType
from app.services.work_order_service import (
    WorkOrderServiceError,
    cancel_work_order,
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

    repair_type_ids = [repair_type.id for repair_type in repair_types]

    if not repair_type_ids:
        return repair_types, {}

    repair_type_specialties = (
        RepairTypeSpecialty.query
        .filter(RepairTypeSpecialty.repair_type_id.in_(repair_type_ids))
        .all()
    )

    specialties_by_repair_type = {}

    for row in repair_type_specialties:
        specialties_by_repair_type.setdefault(row.repair_type_id, set()).add(row.specialty_id)

    all_specialty_ids = {
        row.specialty_id
        for row in repair_type_specialties
        if row.specialty_id
    }

    mechanics_by_specialty = {}

    if all_specialty_ids:
        mechanic_assignments = (
            db.session.query(MechanicSpecialtyAssignment, Mechanic)
            .join(Mechanic, Mechanic.id == MechanicSpecialtyAssignment.mechanic_id)
            .filter(
                Mechanic.site_id == site_id,
                Mechanic.is_active.is_(True),
                MechanicSpecialtyAssignment.specialty_id.in_(all_specialty_ids),
            )
            .order_by(Mechanic.name.asc())
            .all()
        )

        for assignment, mechanic in mechanic_assignments:
            mechanics_by_specialty.setdefault(assignment.specialty_id, []).append(mechanic)

    repair_type_mechanics_map = {}

    for repair_type in repair_types:
        specialty_ids = specialties_by_repair_type.get(repair_type.id, set())

        mechanics_map = {}

        for specialty_id in specialty_ids:
            for mechanic in mechanics_by_specialty.get(specialty_id, []):
                mechanics_map[mechanic.id] = {
                    "id": mechanic.id,
                    "name": mechanic.name,
                    "code": mechanic.code,
                }

        repair_type_mechanics_map[str(repair_type.id)] = sorted(
            mechanics_map.values(),
            key=lambda item: item["name"],
        )

    return repair_types, repair_type_mechanics_map


# =========================================================
# LISTADO DE ÓRDENES DE TRABAJO
# =========================================================
@work_order_bp.route("/", methods=["GET"])
@login_required
@permission_required("ot")
def list_work_orders():
    status = (request.args.get("status") or "").strip()
    ot_number = (request.args.get("ot_number") or "").strip()

    return render_template(
        "work_orders/index.html",
        title="Órdenes de trabajo",
        subtitle="Consulte órdenes de trabajo por estado o número de OT.",
        work_orders=[],
        pagination=None,
        status=status,
        ot_number=ot_number,
    )

# =========================================================
# PARCIAL AJAX - LISTADO DE ÓRDENES DE TRABAJO
# =========================================================
@work_order_bp.route("/partial/list", methods=["GET"])
@login_required
@permission_required("ot")
def list_work_orders_partial():
    status = (request.args.get("status") or "").strip()
    ot_number = (request.args.get("ot_number") or "").strip()
    page = request.args.get("page", 1, type=int)

    try:
        query = (
            WorkOrder.query
            .options(
                joinedload(WorkOrder.warehouse),
                joinedload(WorkOrder.equipment),
                joinedload(WorkOrder.responsible_user),
            )
        )

        active_site_id = session.get("active_site_id")

        if active_site_id:
            query = query.filter(
                WorkOrder.site_id == int(active_site_id)
            )

        if status:
            query = query.filter(
                WorkOrder.status == status
            )

        if ot_number:
            query = query.filter(
                WorkOrder.number.ilike(f"{ot_number}%")
            )

        pagination = (
            query
            .order_by(
                WorkOrder.created_at.desc(),
                WorkOrder.id.desc(),
            )
            .paginate(
                page=page,
                per_page=20,
                error_out=False,
            )
        )

        return render_template(
            "work_orders/_list.html",
            work_orders=pagination.items,
            pagination=pagination,
            status=status,
            ot_number=ot_number,
        )

    except Exception as exc:
        print(f"[LIST OT PARTIAL ERROR] {exc}")
        return ""


@work_order_bp.route("/create", methods=["GET"])
@login_required
@permission_required("ot")
def create_work_order_page():
    active_site_id = session.get("active_site_id")

    sites = Site.query.filter_by(is_active=True).order_by(Site.name).all()

    warehouses_query = (
        Warehouse.query
        .filter(Warehouse.is_active.is_(True))
        .order_by(Warehouse.name)
    )

    if active_site_id:
        warehouses_query = warehouses_query.filter(
            Warehouse.site_id == int(active_site_id)
        )

    warehouses = warehouses_query.all()

    equipment_types = (
        EquipmentType.query
        .filter(EquipmentType.is_active.is_(True))
        .order_by(EquipmentType.name.asc())
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
        equipments=[],
        equipment_types=equipment_types,
        repair_types=repair_types,
        repair_type_mechanics_map=repair_type_mechanics_map,
    )

# =========================================================
# CREAR OT
# =========================================================
# =========================================================
# CREAR OT
# =========================================================
@work_order_bp.route("/", methods=["POST"])
@login_required
@permission_required("ot")
def create_work_order_action():
    try:
        site_id = session.get("active_site_id")

        warehouse_id = (
            request.form.get("warehouse_id")
            or ""
        ).strip()

        description = (
            request.form.get("description")
            or ""
        ).strip()

        repair_type_ids = request.form.getlist(
            "repair_type_id[]"
        )

        mechanic_ids = request.form.getlist(
            "mechanic_id[]"
        )

        equipment_type_id_raw = (
            request.form.get("equipment_type_id")
            or ""
        ).strip()

        equipment_id_raw = (
            request.form.get("equipment_id")
            or ""
        ).strip()

        container_number = (
            request.form.get("container_number")
            or ""
        ).strip().upper()

        if not site_id:
            raise ValueError(
                "No hay un predio activo seleccionado."
            )

        site_id = int(site_id)

        if not warehouse_id:
            raise ValueError(
                "La bodega es obligatoria."
            )

        warehouse_id = int(warehouse_id)

        warehouse = (
            Warehouse.query
            .filter(
                Warehouse.id == warehouse_id,
                Warehouse.site_id == site_id,
                Warehouse.is_active.is_(True),
            )
            .first()
        )

        if not warehouse:
            raise ValueError(
                "La bodega seleccionada no existe, está inactiva "
                "o no pertenece al predio actual."
            )

        # =====================================================
        # VALIDAR TRABAJOS Y MECÁNICOS
        # =====================================================

        task_rows = []

        max_task_rows = max(
            len(repair_type_ids),
            len(mechanic_ids),
        )

        for index in range(max_task_rows):
            repair_type_id_raw = (
                repair_type_ids[index].strip()
                if index < len(repair_type_ids)
                else ""
            )

            mechanic_id_raw = (
                mechanic_ids[index].strip()
                if index < len(mechanic_ids)
                else ""
            )

            # Ignorar filas completamente vacías.
            if not repair_type_id_raw and not mechanic_id_raw:
                continue

            if not repair_type_id_raw:
                raise ValueError(
                    f"Debe seleccionar el tipo de reparación "
                    f"en el trabajo {index + 1}."
                )

            if not mechanic_id_raw:
                raise ValueError(
                    f"Debe seleccionar el mecánico "
                    f"en el trabajo {index + 1}."
                )

            repair_type = (
                RepairType.query
                .filter(
                    RepairType.id == int(repair_type_id_raw),
                    RepairType.is_active.is_(True),
                )
                .first()
            )

            if not repair_type:
                raise ValueError(
                    f"El tipo de reparación del trabajo "
                    f"{index + 1} no existe o está inactivo."
                )

            mechanic = (
                Mechanic.query
                .filter(
                    Mechanic.id == int(mechanic_id_raw),
                    Mechanic.site_id == site_id,
                    Mechanic.is_active.is_(True),
                )
                .first()
            )

            if not mechanic:
                raise ValueError(
                    f"El mecánico del trabajo {index + 1} "
                    f"no existe, está inactivo o pertenece "
                    f"a otro predio."
                )

            task_rows.append(
                {
                    "repair_type_id": repair_type.id,
                    "repair_type_name": repair_type.name,
                    "mechanic_id": mechanic.id,
                }
            )

        if not task_rows:
            raise ValueError(
                "Debe agregar al menos un trabajo con su mecánico."
            )

        # =====================================================
        # VALIDAR EQUIPO
        # =====================================================

        selected_equipment_id = None
        equipment_code_snapshot = None

        if equipment_type_id_raw:
            equipment_type = (
                EquipmentType.query
                .filter(
                    EquipmentType.id
                    == int(equipment_type_id_raw),
                    EquipmentType.is_active.is_(True),
                )
                .first()
            )

            if not equipment_type:
                raise ValueError(
                    "El tipo de equipo seleccionado no existe "
                    "o está inactivo."
                )

            equipment_type_code = (
                equipment_type.code
                or ""
            ).strip().upper()

            # =============================================
            # CONTENEDOR: INGRESO MANUAL
            # =============================================
            if equipment_type_code == "CONTENEDOR":
                if not re.fullmatch(
                    r"[A-Z]{4}-\d{6}-\d",
                    container_number,
                ):
                    raise ValueError(
                        "Ingrese un contenedor con formato correcto: "
                        "ABCD-123456-7."
                    )

                selected_equipment_id = None
                equipment_code_snapshot = container_number

            # =============================================
            # RESTO DE EQUIPOS: DEBEN EXISTIR EN LA BD
            # =============================================
            else:
                if not equipment_id_raw:
                    raise ValueError(
                        "Debe seleccionar un equipo registrado "
                        "para el tipo indicado."
                    )

                selected_equipment = (
                    Equipment.query
                    .filter(
                        Equipment.id == int(equipment_id_raw),
                        Equipment.equipment_type_id
                        == equipment_type.id,
                        Equipment.is_active.is_(True),
                    )
                    .first()
                )

                if not selected_equipment:
                    raise ValueError(
                        "El equipo seleccionado no existe, está inactivo, "
                        "pertenece a otro predio o no corresponde "
                        "al tipo indicado."
                    )

                selected_equipment_id = (
                    selected_equipment.id
                )

                # El código se obtiene desde la base de datos.
                # No se confía en el valor enviado por el navegador.
                equipment_code_snapshot = (
                    selected_equipment.code
                    or ""
                ).strip()

                if not equipment_code_snapshot:
                    raise ValueError(
                        "El equipo seleccionado no tiene código registrado."
                    )

        # Si no seleccionó tipo, la OT puede quedar sin equipo.
        else:
            selected_equipment_id = None
            equipment_code_snapshot = None

        # =====================================================
        # CREAR OT CON EL PRIMER TRABAJO
        # =====================================================

        first_task = task_rows[0]

        work_order = create_work_order(
            number="",
            site_id=site_id,
            warehouse_id=warehouse_id,
            responsible_user_id=current_user.id,
            created_by_user_id=current_user.id,
            repair_type_id=(
                first_task["repair_type_id"]
            ),
            mechanic_id=(
                first_task["mechanic_id"]
            ),
            task_title=(
                first_task["repair_type_name"]
                or "Trabajo"
            ),
            task_description=None,
            description=description or None,
            equipment_id=selected_equipment_id,
            equipment_code_snapshot=(
                equipment_code_snapshot
            ),
            commit=False,
        )

        db.session.flush()

        # =====================================================
        # CREAR TRABAJOS ADICIONALES
        # =====================================================

        for task_row in task_rows[1:]:
            create_task_line(
                work_order_id=work_order.id,
                repair_type_id=(
                    task_row["repair_type_id"]
                ),
                title=(
                    task_row["repair_type_name"]
                    or "Trabajo"
                ),
                description=None,
                assigned_mechanic_id=(
                    task_row["mechanic_id"]
                ),
                created_by_user_id=current_user.id,
                commit=False,
            )

        db.session.commit()

        flash(
            f"Orden de trabajo {work_order.number} "
            f"creada correctamente.",
            "success",
        )

        return redirect(
            url_for(
                "work_orders.get_work_order",
                work_order_id=work_order.id,
            )
        )

    except (
        WorkOrderServiceError,
        WorkOrderTaskServiceError,
        ValueError,
        TypeError,
    ) as exc:
        db.session.rollback()

        flash(
            str(exc),
            "danger",
        )

        return redirect(
            url_for(
                "work_orders.create_work_order_page"
            )
        )

    except Exception as exc:
        db.session.rollback()

        print(
            "[CREATE OT ERROR] "
            f"{type(exc).__name__}: {exc}"
        )

        flash(
            "Error interno al crear la OT.",
            "danger",
        )

        return redirect(
            url_for(
                "work_orders.create_work_order_page"
            )
        )

@work_order_bp.route(
    "/equipment/search",
    methods=["GET"],
)
@login_required
@permission_required("ot")
def search_equipment_for_work_order():
    """
    Devuelve equipos activos según el tipo seleccionado.

    Reglas:
    - CONTENEDOR:
        no consulta equipos porque el número se ingresa manualmente.
    - CHASIS:
        requiere al menos 2 caracteres de búsqueda.
    - Cualquier otro tipo:
        devuelve todos los equipos activos de ese tipo.
    - Los equipos son globales, no se filtran por predio.
    """

    try:
        equipment_type_id = request.args.get(
            "equipment_type_id",
            type=int,
        )

        q = (
            request.args.get("q")
            or ""
        ).strip()

        if not equipment_type_id:
            return jsonify(
                {
                    "ok": False,
                    "message": (
                        "Debe seleccionar un tipo de equipo."
                    ),
                    "equipment_type_code": "",
                    "items": [],
                }
            ), 400

        equipment_type = (
            EquipmentType.query
            .filter(
                EquipmentType.id == equipment_type_id,
                EquipmentType.is_active.is_(True),
            )
            .first()
        )

        if not equipment_type:
            return jsonify(
                {
                    "ok": False,
                    "message": (
                        "El tipo de equipo no existe "
                        "o está inactivo."
                    ),
                    "equipment_type_code": "",
                    "items": [],
                }
            ), 404

        equipment_type_code = (
            equipment_type.code
            or ""
        ).strip().upper()

        # =====================================================
        # CONTENEDOR: INGRESO MANUAL
        # =====================================================

        if equipment_type_code == "CONTENEDOR":
            print(
                "[EQUIPMENT SEARCH] "
                f"type_id={equipment_type.id} "
                f"type_code={equipment_type_code} "
                "mode=manual_container "
                "count=0"
            )

            return jsonify(
                {
                    "ok": True,
                    "message": "",
                    "equipment_type_code": (
                        equipment_type_code
                    ),
                    "items": [],
                }
            )

        # =====================================================
        # CHASIS: BÚSQUEDA AJAX POR TEXTO
        # =====================================================

        if (
            equipment_type_code == "CHASIS"
            and len(q) < 2
        ):
            print(
                "[EQUIPMENT SEARCH] "
                f"type_id={equipment_type.id} "
                f"type_code={equipment_type_code} "
                f"query={q!r} "
                "mode=chassis_waiting_query "
                "count=0"
            )

            return jsonify(
                {
                    "ok": True,
                    "message": "",
                    "equipment_type_code": (
                        equipment_type_code
                    ),
                    "items": [],
                }
            )

        # =====================================================
        # CONSULTA GENERAL
        # =====================================================

        query = (
            Equipment.query
            .filter(
                Equipment.equipment_type_id
                == equipment_type.id,
                Equipment.is_active.is_(True),
            )
        )

        if q:
            like_prefix = f"{q}%"
            like_contains = f"%{q}%"

            query = query.filter(
                db.or_(
                    Equipment.code.ilike(
                        like_prefix
                    ),
                    Equipment.description.ilike(
                        like_contains
                    ),
                )
            )

        result_limit = (
            20
            if equipment_type_code == "CHASIS"
            else 200
        )

        equipments = (
            query
            .order_by(
                Equipment.code.asc(),
                Equipment.description.asc(),
                Equipment.id.asc(),
            )
            .limit(result_limit)
            .all()
        )

        items = []

        for equipment in equipments:
            code = (
                equipment.code
                or ""
            ).strip()

            description = (
                equipment.description
                or ""
            ).strip()

            label = code

            if description:
                label = (
                    f"{code} - {description}"
                )

            items.append(
                {
                    "id": int(equipment.id),
                    "code": code,
                    "description": description,
                    "label": label,
                    "equipment_type_id": (
                        int(
                            equipment.equipment_type_id
                        )
                        if equipment.equipment_type_id
                        else None
                    ),
                }
            )

        print(
            "[EQUIPMENT SEARCH] "
            f"type_id={equipment_type.id} "
            f"type_code={equipment_type_code} "
            f"query={q!r} "
            f"count={len(items)} "
            f"codes={[item['code'] for item in items[:20]]}"
        )

        return jsonify(
            {
                "ok": True,
                "message": "",
                "equipment_type_code": (
                    equipment_type_code
                ),
                "items": items,
            }
        )

    except Exception as exc:
        db.session.rollback()

        print(
            "[EQUIPMENT SEARCH ERROR] "
            f"{type(exc).__name__}: {exc}"
        )

        return jsonify(
            {
                "ok": False,
                "message": (
                    "Ocurrió un error al cargar "
                    "los equipos."
                ),
                "equipment_type_code": "",
                "items": [],
            }
        ), 500

# =========================================================
# DETALLE OT
# =========================================================
@work_order_bp.route("/<int:work_order_id>", methods=["GET"])
@login_required
@permission_required("ot")
def get_work_order(work_order_id: int):
    try:
        source = (request.args.get("source") or "").strip()

        work_order = (
            WorkOrder.query
            .options(
                joinedload(WorkOrder.warehouse),
                joinedload(WorkOrder.responsible_user),
            )
            .filter(WorkOrder.id == work_order_id)
            .first()
        )

        if not work_order:
            raise ValueError(
                "Orden de trabajo no encontrada."
            )

        return render_template(
            "work_orders/detail.html",
            title="Detalle de Orden de Trabajo",
            subtitle=(
                "Consulte la información general, "
                "líneas y acciones de la OT."
            ),
            work_order=work_order,
            source=source,
        )

    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(
            url_for("work_orders.list_work_orders")
        )

    except Exception as exc:
        print(f"[ERROR OT DETAIL] {exc}")
        flash(
            "Error al cargar la orden de trabajo.",
            "danger",
        )
        return redirect(
            url_for("work_orders.list_work_orders")
        )

    except ValueError as exc:
        flash(str(exc), "danger")

        return redirect(
            url_for("work_orders.list_work_orders")
        )

    except Exception as exc:
        print(f"[ERROR OT DETAIL] {exc}")

        flash(
            "Error al cargar la orden de trabajo.",
            "danger",
        )

        return redirect(
            url_for("work_orders.list_work_orders")
        )

@work_order_bp.route("/<int:work_order_id>/partial/lines", methods=["GET"])
@login_required
@permission_required("ot")
def get_work_order_lines_partial(work_order_id: int):
    try:
        work_order = (
            WorkOrder.query
            .options(
                selectinload(WorkOrder.lines)
                    .joinedload(WorkOrderLine.article),

                selectinload(WorkOrder.lines)
                    .joinedload(WorkOrderLine.received_by_user),

                selectinload(WorkOrder.lines)
                    .joinedload(WorkOrderLine.delivered_by_user),

                selectinload(WorkOrder.lines)
                    .joinedload(WorkOrderLine.request_line)
                    .joinedload(
                        WorkOrderRequestLine.work_order_request
                    )
                    .joinedload(WorkOrderRequest.mechanic),

                selectinload(WorkOrder.lines)
                    .joinedload(WorkOrderLine.request_line)
                    .joinedload(
                        WorkOrderRequestLine.work_order_request
                    )
                    .joinedload(
                        WorkOrderRequest.approved_by_user
                    ),

                selectinload(WorkOrder.lines)
                    .selectinload(
                        WorkOrderLine.delete_requests
                    ),
            )
            .filter(WorkOrder.id == work_order_id)
            .first()
        )

        if not work_order:
            return "<div class='alert alert-danger'>Orden de trabajo no encontrada.</div>", 404

        latest_delete_request_map = {}

        for line in work_order.lines:
            latest_delete = None

            if line.delete_requests:
                latest_delete = max(
                    line.delete_requests,
                    key=lambda x: x.created_at or datetime.min,
                )

            latest_delete_request_map[line.id] = latest_delete

        return render_template(
            "work_orders/partials/_lines.html",
            work_order=work_order,
            latest_delete_request_map=latest_delete_request_map,
        )

    except Exception as exc:
        print(f"[OT LINES PARTIAL ERROR] {exc}")
        return "<div class='alert alert-danger'>Error al cargar líneas de la OT.</div>", 500
    
@work_order_bp.route("/<int:work_order_id>/partial/requests", methods=["GET"])
@login_required
@permission_required("ot")
def get_work_order_requests_partial(work_order_id: int):
    try:
        source = (request.args.get("source") or "").strip()

        work_order = (
            WorkOrder.query
            .filter(WorkOrder.id == work_order_id)
            .first()
        )

        if not work_order:
            return "<div class='alert alert-danger'>Orden de trabajo no encontrada.</div>", 404

        existing_request_line_ids = {
            row[0]
            for row in (
                db.session.query(WorkOrderLine.request_line_id)
                .filter(
                    WorkOrderLine.work_order_id == work_order_id,
                    WorkOrderLine.request_line_id.isnot(None),
                )
                .all()
            )
        }

        requests = (
            WorkOrderRequest.query
            .options(
                selectinload(WorkOrderRequest.lines)
                    .joinedload(WorkOrderRequestLine.article),

                joinedload(
                    WorkOrderRequest.requested_by_user
                ),

                joinedload(
                    WorkOrderRequest.approved_by_user
                ),

                joinedload(
                    WorkOrderRequest.sent_to_warehouse_by_user
                ),
            )
            .filter(
                WorkOrderRequest.work_order_id == work_order_id,
                WorkOrderRequest.sent_to_warehouse_at.isnot(None),
            )
            .order_by(WorkOrderRequest.created_at.desc())
            .all()
        )

        visible_requests = []
        stock_by_article_id = {}

        if source == "dashboard":
            article_ids = set()

            for req in requests:
                for line in req.lines:
                    if line.line_status == "CANCELADA":
                        continue

                    if (
                        hasattr(line, "manager_review_status")
                        and line.manager_review_status != "APROBADA"
                    ):
                        continue

                    if line.id in existing_request_line_ids:
                        continue

                    if line.article_id:
                        article_ids.add(line.article_id)

            if article_ids:
                stocks = (
                    WarehouseStock.query
                    .filter(
                        WarehouseStock.warehouse_id == work_order.warehouse_id,
                        WarehouseStock.article_id.in_(article_ids),
                    )
                    .all()
                )

                stock_by_article_id = {
                    stock.article_id: stock
                    for stock in stocks
                }

        for req in requests:
            request_lines_for_view = []

            for line in req.lines:
                if line.line_status == "CANCELADA":
                    continue

                if (
                    hasattr(line, "manager_review_status")
                    and line.manager_review_status != "APROBADA"
                ):
                    continue

                if line.id in existing_request_line_ids:
                    continue

                if source == "dashboard":
                    stock = stock_by_article_id.get(line.article_id)

                    available_qty = (
                        Decimal(str(stock.available_quantity))
                        if stock and stock.available_quantity
                        else Decimal("0")
                    )

                    remaining = (
                        Decimal(str(line.quantity_requested or 0))
                        - Decimal(str(line.quantity_attended or 0))
                    )

                    line.stock_available = available_qty
                    line.suggested_attend_quantity = (
                        min(available_qty, remaining)
                        if remaining > 0
                        else Decimal("0")
                    )
                    line.warehouse_action_enabled = available_qty > 0 and remaining > 0
                    line.location_label = (
                        stock.location_name
                        if stock and hasattr(stock, "location_name")
                        else "-"
                    )

                request_lines_for_view.append(line)

            if request_lines_for_view:
                req.filtered_lines = request_lines_for_view
                visible_requests.append(req)

        return render_template(
            "work_orders/partials/_requests.html",
            visible_requests=visible_requests,
            source=source,
        )

    except Exception as exc:
        print(f"[OT REQUESTS PARTIAL ERROR] {exc}")
        return "<div class='alert alert-danger'>Error al cargar solicitudes de artículos.</div>", 500

@work_order_bp.route(
    "/<int:work_order_id>/partial/tasks",
    methods=["GET"],
)
@login_required
@permission_required("ot")
def get_work_order_tasks_partial(work_order_id: int):
    try:
        work_order = db.session.get(
            WorkOrder,
            work_order_id,
        )

        if not work_order:
            return (
                "<div class='alert alert-danger'>"
                "Orden de trabajo no encontrada."
                "</div>",
                404,
            )

        can_manage_tasks = current_user.has_permission(
            "ot_trabajos"
        )

        task_lines = (
            WorkOrderTaskLine.query
            .options(
                joinedload(
                    WorkOrderTaskLine.assigned_mechanic
                ),
                joinedload(
                    WorkOrderTaskLine.repair_type
                ),
            )
            .filter(
                WorkOrderTaskLine.work_order_id
                == work_order.id
            )
            .order_by(
                WorkOrderTaskLine.created_at.asc(),
                WorkOrderTaskLine.id.asc(),
            )
            .all()
        )

        repair_types = []
        repair_type_mechanics_map = {}

        if can_manage_tasks:
            (
                repair_types,
                repair_type_mechanics_map,
            ) = _build_repair_type_mechanics_map(
                site_id=work_order.site_id
            )

        return render_template(
            "work_orders/partials/_tasks.html",
            work_order=work_order,
            repair_types=repair_types,
            repair_type_mechanics_map=(
                repair_type_mechanics_map
            ),
            task_lines=task_lines,
            can_manage_tasks=can_manage_tasks,
        )

    except Exception as exc:
        print(
            f"[OT TASKS PARTIAL ERROR] "
            f"work_order_id={work_order_id} "
            f"error={exc}"
        )

        return (
            "<div class='alert alert-danger'>"
            "Error al cargar trabajos de la OT."
            "</div>",
            500,
        )
# =========================================================
# CREAR LÍNEA DE TRABAJO EN OT
# =========================================================
@work_order_bp.route("/<int:work_order_id>/tasks", methods=["POST"])
@login_required
@permission_required("ot_trabajos")
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
@permission_required("ot")
def add_line_to_work_order(work_order_id: int):
    flash("Las líneas deben generarse desde solicitudes (flujo correcto).", "warning")
    return redirect(url_for("work_orders.get_work_order", work_order_id=work_order_id))


# =========================================================
# FINALIZAR OT
# =========================================================
@work_order_bp.route("/<int:work_order_id>/finalize", methods=["POST"])
@login_required
@permission_required("ot")
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
@permission_required("ot")
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
# ANULAR OT
# =========================================================
@work_order_bp.route("/<int:work_order_id>/cancel", methods=["POST"])
@login_required
@permission_required("ot_anular")
def cancel_work_order_action(work_order_id: int):
    try:
        reason = (
            request.form.get("reason")
            or ""
        ).strip()

        cancel_work_order(
            work_order_id=work_order_id,
            performed_by_user_id=current_user.id,
            reason=reason,
            commit=True,
        )

        flash(
            "Orden de trabajo anulada correctamente.",
            "success",
        )

    except WorkOrderServiceError as exc:
        db.session.rollback()

        flash(
            str(exc),
            "danger",
        )

    except Exception as exc:
        db.session.rollback()

        print(
            f"[CANCEL OT ERROR] "
            f"work_order_id={work_order_id} "
            f"error={exc}"
        )

        flash(
            "Error interno al anular la OT.",
            "danger",
        )

    return redirect(
        url_for(
            "work_orders.get_work_order",
            work_order_id=work_order_id,
        )
    )

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
@permission_required("ot_trabajos")
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
@permission_required("ot_trabajos")
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
@permission_required("ot_trabajos")
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