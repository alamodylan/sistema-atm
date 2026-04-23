from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models.mechanic_specialty import MechanicSpecialty
from app.models.repair_type import RepairType
from app.models.repair_type_specialty import RepairTypeSpecialty

repair_type_bp = Blueprint("repair_types", __name__, url_prefix="/repair-types")


@repair_type_bp.route("/", methods=["GET"])
@login_required
def index():
    try:
        repair_types = (
            RepairType.query
            .order_by(RepairType.name.asc())
            .all()
        )

        specialties = (
            MechanicSpecialty.query
            .filter(MechanicSpecialty.is_active.is_(True))
            .order_by(MechanicSpecialty.name.asc())
            .all()
        )

        return render_template(
            "repair_types/index.html",
            title="Tipos de reparación",
            subtitle="Gestione tipos de reparación y las especialidades permitidas.",
            repair_types=repair_types,
            specialties=specialties,
        )

    except Exception:
        flash("Error al cargar los tipos de reparación.", "danger")
        return render_template(
            "repair_types/index.html",
            title="Tipos de reparación",
            subtitle="Gestione tipos de reparación y las especialidades permitidas.",
            repair_types=[],
            specialties=[],
        )


@repair_type_bp.route("/create", methods=["POST"])
@login_required
def create():
    try:
        code = (request.form.get("code") or "").strip().upper()
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()
        specialty_ids = request.form.getlist("specialty_ids")

        if not code or not name:
            raise ValueError("El código y el nombre son obligatorios.")

        existing_code = RepairType.query.filter_by(code=code).first()
        if existing_code:
            raise ValueError("Ya existe un tipo de reparación con ese código.")

        existing_name = RepairType.query.filter_by(name=name).first()
        if existing_name:
            raise ValueError("Ya existe un tipo de reparación con ese nombre.")

        repair_type = RepairType(
            code=code,
            name=name,
            description=description or None,
            is_active=True,
        )

        db.session.add(repair_type)
        db.session.flush()

        parsed_ids = set()
        for specialty_id in specialty_ids:
            try:
                parsed_ids.add(int(specialty_id))
            except (TypeError, ValueError):
                continue

        valid_specialties = (
            MechanicSpecialty.query
            .filter(
                MechanicSpecialty.id.in_(parsed_ids),
                MechanicSpecialty.is_active.is_(True),
            )
            .all()
        ) if parsed_ids else []

        for specialty in valid_specialties:
            db.session.add(
                RepairTypeSpecialty(
                    repair_type_id=repair_type.id,
                    specialty_id=specialty.id,
                )
            )

        db.session.commit()
        flash("Tipo de reparación creado correctamente.", "success")
        return redirect(url_for("repair_types.index"))

    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(url_for("repair_types.index"))

    except Exception:
        db.session.rollback()
        flash("Error al crear el tipo de reparación.", "danger")
        return redirect(url_for("repair_types.index"))


@repair_type_bp.route("/<int:repair_type_id>", methods=["GET"])
@login_required
def detail(repair_type_id: int):
    try:
        repair_type = RepairType.query.get_or_404(repair_type_id)

        specialties = (
            MechanicSpecialty.query
            .filter(MechanicSpecialty.is_active.is_(True))
            .order_by(MechanicSpecialty.name.asc())
            .all()
        )

        assigned_specialty_ids = {
            row.specialty_id
            for row in RepairTypeSpecialty.query.filter_by(repair_type_id=repair_type.id).all()
        }

        return render_template(
            "repair_types/detail.html",
            title="Detalle tipo de reparación",
            subtitle="Consulte la información del tipo de reparación y administre sus especialidades.",
            repair_type=repair_type,
            specialties=specialties,
            assigned_specialty_ids=assigned_specialty_ids,
        )

    except Exception:
        flash("Error al cargar el tipo de reparación.", "danger")
        return redirect(url_for("repair_types.index"))


@repair_type_bp.route("/<int:repair_type_id>/specialties", methods=["POST"])
@login_required
def update_specialties(repair_type_id: int):
    try:
        repair_type = RepairType.query.get_or_404(repair_type_id)
        specialty_ids = request.form.getlist("specialty_ids")

        parsed_ids = set()
        for specialty_id in specialty_ids:
            try:
                parsed_ids.add(int(specialty_id))
            except (TypeError, ValueError):
                continue

        valid_specialties = (
            MechanicSpecialty.query
            .filter(
                MechanicSpecialty.id.in_(parsed_ids),
                MechanicSpecialty.is_active.is_(True),
            )
            .all()
        ) if parsed_ids else []

        valid_ids = {specialty.id for specialty in valid_specialties}

        RepairTypeSpecialty.query.filter_by(
            repair_type_id=repair_type.id
        ).delete(synchronize_session=False)

        for specialty_id in valid_ids:
            db.session.add(
                RepairTypeSpecialty(
                    repair_type_id=repair_type.id,
                    specialty_id=specialty_id,
                )
            )

        db.session.commit()
        flash("Especialidades del tipo de reparación actualizadas correctamente.", "success")
        return redirect(url_for("repair_types.detail", repair_type_id=repair_type.id))

    except Exception:
        db.session.rollback()
        flash("Error al actualizar especialidades del tipo de reparación.", "danger")
        return redirect(url_for("repair_types.detail", repair_type_id=repair_type_id))


@repair_type_bp.route("/<int:repair_type_id>/toggle", methods=["GET"])
@login_required
def toggle(repair_type_id: int):
    try:
        repair_type = RepairType.query.get_or_404(repair_type_id)

        repair_type.is_active = not repair_type.is_active
        db.session.commit()

        flash("Estado del tipo de reparación actualizado correctamente.", "success")
        return redirect(url_for("repair_types.index"))

    except Exception:
        db.session.rollback()
        flash("Error al cambiar el estado del tipo de reparación.", "danger")
        return redirect(url_for("repair_types.index"))