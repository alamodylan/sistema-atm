from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required
from app.utils.permissions import permission_required

from app.services.equipment_service import (
    EquipmentServiceError,
    create_equipment,
    create_equipment_type,
    get_equipment_or_404,
    get_equipment_type_or_404,
    list_equipment,
    list_equipment_types,
    toggle_equipment_status,
    toggle_equipment_type_status,
    update_equipment,
    update_equipment_type,
)

equipment_bp = Blueprint(
    "equipment",
    __name__,
    url_prefix="/equipment",
)


@equipment_bp.route("/")
@login_required
@permission_required("equipos")
def index():
    equipment_list = list_equipment(include_inactive=True)
    equipment_types = list_equipment_types(include_inactive=True)

    return render_template(
        "equipment/index.html",
        equipment_list=equipment_list,
        equipment_types=equipment_types,
    )


@equipment_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    equipment_types = list_equipment_types(include_inactive=False)

    if request.method == "POST":
        try:
            create_equipment(
                code=request.form.get("code"),
                equipment_type_id=request.form.get("equipment_type_id"),
                description=request.form.get("description"),
                axle_count=request.form.get("axle_count"),
                size_label=request.form.get("size_label"),
            )

            flash("Equipo creado correctamente.", "success")
            return redirect(url_for("equipment.index"))

        except EquipmentServiceError as exc:
            flash(str(exc), "danger")

    return render_template(
        "equipment/form.html",
        equipment=None,
        equipment_types=equipment_types,
        form_title="Nuevo equipo",
        submit_label="Crear equipo",
    )


@equipment_bp.route("/<int:equipment_id>/edit", methods=["GET", "POST"])
@login_required
def edit(equipment_id):
    equipment = get_equipment_or_404(equipment_id)
    equipment_types = list_equipment_types(include_inactive=False)

    if request.method == "POST":
        try:
            update_equipment(
                equipment_id=equipment.id,
                code=request.form.get("code"),
                equipment_type_id=request.form.get("equipment_type_id"),
                description=request.form.get("description"),
                axle_count=request.form.get("axle_count"),
                size_label=request.form.get("size_label"),
                is_active=request.form.get("is_active") == "on",
            )

            flash("Equipo actualizado correctamente.", "success")
            return redirect(url_for("equipment.index"))

        except EquipmentServiceError as exc:
            flash(str(exc), "danger")

    return render_template(
        "equipment/form.html",
        equipment=equipment,
        equipment_types=equipment_types,
        form_title=f"Editar equipo {equipment.code}",
        submit_label="Guardar cambios",
    )


@equipment_bp.route("/<int:equipment_id>/toggle-active", methods=["POST"])
@login_required
def toggle_active(equipment_id):
    toggle_equipment_status(equipment_id)
    flash("Estado del equipo actualizado correctamente.", "success")
    return redirect(url_for("equipment.index"))


@equipment_bp.route("/types", methods=["GET"])
@login_required
def types_index():
    equipment_types = list_equipment_types(include_inactive=True)

    return render_template(
        "equipment/types.html",
        equipment_types=equipment_types,
        equipment_type=None,
        form_title="Nuevo tipo de equipo",
        submit_label="Crear tipo",
    )


@equipment_bp.route("/types/create", methods=["POST"])
@login_required
def types_create():
    try:
        create_equipment_type(
            code=request.form.get("code"),
            name=request.form.get("name"),
            description=request.form.get("description"),
        )

        flash("Tipo de equipo creado correctamente.", "success")

    except EquipmentServiceError as exc:
        flash(str(exc), "danger")

    return redirect(url_for("equipment.types_index"))


@equipment_bp.route("/types/<int:equipment_type_id>/edit", methods=["GET", "POST"])
@login_required
def types_edit(equipment_type_id):
    equipment_type = get_equipment_type_or_404(equipment_type_id)
    equipment_types = list_equipment_types(include_inactive=True)

    if request.method == "POST":
        try:
            update_equipment_type(
                equipment_type_id=equipment_type.id,
                code=request.form.get("code"),
                name=request.form.get("name"),
                description=request.form.get("description"),
                is_active=request.form.get("is_active") == "on",
            )

            flash("Tipo de equipo actualizado correctamente.", "success")
            return redirect(url_for("equipment.types_index"))

        except EquipmentServiceError as exc:
            flash(str(exc), "danger")

    return render_template(
        "equipment/types.html",
        equipment_types=equipment_types,
        equipment_type=equipment_type,
        form_title=f"Editar tipo {equipment_type.code}",
        submit_label="Guardar cambios",
    )


@equipment_bp.route("/types/<int:equipment_type_id>/toggle-active", methods=["POST"])
@login_required
def types_toggle_active(equipment_type_id):
    toggle_equipment_type_status(equipment_type_id)
    flash("Estado del tipo de equipo actualizado correctamente.", "success")
    return redirect(url_for("equipment.types_index"))