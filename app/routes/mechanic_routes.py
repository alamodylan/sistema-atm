from flask import Blueprint, render_template, request, redirect, url_for, flash, session, make_response
from flask_login import login_required

from app.extensions import db
from app.models.mechanic import Mechanic
from app.models.mechanic_specialty import MechanicSpecialty
from app.models.mechanic_specialty_assignment import MechanicSpecialtyAssignment
from app.services.badge_pdf_service import build_mechanic_badge_pdf

mechanic_bp = Blueprint("mechanics", __name__, url_prefix="/mechanics")


def _get_active_site_id() -> int:
    active_site_id = session.get("active_site_id")
    if not active_site_id:
        raise ValueError("Debe seleccionar un predio activo para continuar.")
    return int(active_site_id)


def _get_mechanic_for_active_site_or_404(mechanic_id: int, active_site_id: int):
    mechanic = Mechanic.query.filter(
        Mechanic.id == mechanic_id,
        Mechanic.site_id == active_site_id,
    ).first_or_404()
    return mechanic


@mechanic_bp.route("/")
@login_required
def index():
    try:
        active_site_id = _get_active_site_id()

        mechanics = (
            Mechanic.query.filter_by(site_id=active_site_id)
            .order_by(Mechanic.name.asc())
            .all()
        )

        specialties = (
            MechanicSpecialty.query
            .order_by(MechanicSpecialty.name.asc())
            .all()
        )

        return render_template(
            "mechanics/index.html",
            mechanics=mechanics,
            specialties=specialties,
        )

    except ValueError as exc:
        flash(str(exc), "danger")
        return render_template(
            "mechanics/index.html",
            mechanics=[],
            specialties=[],
        )


@mechanic_bp.route("/create", methods=["POST"])
@login_required
def create():
    try:
        active_site_id = _get_active_site_id()

        name = (request.form.get("name") or "").strip()
        code = (request.form.get("code") or "").strip()
        specialty_ids = request.form.getlist("specialty_ids")

        if not name or not code:
            flash("Nombre y código son obligatorios.", "danger")
            return redirect(url_for("mechanics.index"))

        existing = Mechanic.query.filter(
            Mechanic.site_id == active_site_id,
            Mechanic.code == code,
        ).first()
        if existing:
            flash("Ya existe un mecánico con ese código en el predio activo.", "danger")
            return redirect(url_for("mechanics.index"))

        mechanic = Mechanic(
            site_id=active_site_id,
            name=name,
            code=code,
        )

        db.session.add(mechanic)
        db.session.flush()

        valid_specialty_ids = set()
        for specialty_id in specialty_ids:
            try:
                sid = int(specialty_id)
            except (TypeError, ValueError):
                continue
            valid_specialty_ids.add(sid)

        if valid_specialty_ids:
            specialties = MechanicSpecialty.query.filter(
                MechanicSpecialty.id.in_(valid_specialty_ids)
            ).all()

            for specialty in specialties:
                db.session.add(
                    MechanicSpecialtyAssignment(
                        mechanic_id=mechanic.id,
                        specialty_id=specialty.id,
                    )
                )

        db.session.commit()
        flash("Mecánico creado correctamente.", "success")
        return redirect(url_for("mechanics.index"))

    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("mechanics.index"))

    except Exception:
        db.session.rollback()
        flash("Error al crear el mecánico.", "danger")
        return redirect(url_for("mechanics.index"))


@mechanic_bp.route("/specialties/create", methods=["POST"])
@login_required
def create_specialty():
    try:
        code = (request.form.get("code") or "").strip().upper()
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()

        if not code or not name:
            flash("Código y nombre de la especialidad son obligatorios.", "danger")
            return redirect(url_for("mechanics.index"))

        existing_code = MechanicSpecialty.query.filter_by(code=code).first()
        if existing_code:
            flash("Ya existe una especialidad con ese código.", "danger")
            return redirect(url_for("mechanics.index"))

        existing_name = MechanicSpecialty.query.filter_by(name=name).first()
        if existing_name:
            flash("Ya existe una especialidad con ese nombre.", "danger")
            return redirect(url_for("mechanics.index"))

        specialty = MechanicSpecialty(
            code=code,
            name=name,
            description=description or None,
            is_active=True,
        )

        db.session.add(specialty)
        db.session.commit()

        flash("Especialidad creada correctamente.", "success")
        return redirect(url_for("mechanics.index"))

    except Exception:
        db.session.rollback()
        flash("Error al crear la especialidad.", "danger")
        return redirect(url_for("mechanics.index"))


@mechanic_bp.route("/<int:mechanic_id>")
@login_required
def detail(mechanic_id):
    try:
        active_site_id = _get_active_site_id()
        mechanic = _get_mechanic_for_active_site_or_404(mechanic_id, active_site_id)

        all_specialties = (
            MechanicSpecialty.query
            .order_by(MechanicSpecialty.name.asc())
            .all()
        )

        assigned_specialty_ids = {
            row.specialty_id
            for row in MechanicSpecialtyAssignment.query.filter_by(mechanic_id=mechanic.id).all()
        }

        return render_template(
            "mechanics/detail.html",
            mechanic=mechanic,
            all_specialties=all_specialties,
            assigned_specialty_ids=assigned_specialty_ids,
        )

    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("mechanics.index"))


@mechanic_bp.route("/<int:mechanic_id>/specialties", methods=["POST"])
@login_required
def update_specialties(mechanic_id):
    try:
        active_site_id = _get_active_site_id()
        mechanic = _get_mechanic_for_active_site_or_404(mechanic_id, active_site_id)

        specialty_ids = request.form.getlist("specialty_ids")

        parsed_ids = set()
        for specialty_id in specialty_ids:
            try:
                parsed_ids.add(int(specialty_id))
            except (TypeError, ValueError):
                continue

        valid_specialties = MechanicSpecialty.query.filter(
            MechanicSpecialty.id.in_(parsed_ids)
        ).all() if parsed_ids else []

        valid_ids = {specialty.id for specialty in valid_specialties}

        MechanicSpecialtyAssignment.query.filter_by(
            mechanic_id=mechanic.id
        ).delete(synchronize_session=False)

        for specialty_id in valid_ids:
            db.session.add(
                MechanicSpecialtyAssignment(
                    mechanic_id=mechanic.id,
                    specialty_id=specialty_id,
                )
            )

        db.session.commit()
        flash("Especialidades actualizadas correctamente.", "success")
        return redirect(url_for("mechanics.detail", mechanic_id=mechanic.id))

    except Exception:
        db.session.rollback()
        flash("Error al actualizar especialidades del mecánico.", "danger")
        return redirect(url_for("mechanics.detail", mechanic_id=mechanic_id))


@mechanic_bp.route("/<int:mechanic_id>/toggle")
@login_required
def toggle(mechanic_id):
    try:
        active_site_id = _get_active_site_id()
        mechanic = _get_mechanic_for_active_site_or_404(mechanic_id, active_site_id)

        mechanic.is_active = not mechanic.is_active
        db.session.commit()

        flash("Estado del mecánico actualizado correctamente.", "success")
        return redirect(url_for("mechanics.index"))

    except Exception:
        db.session.rollback()
        flash("Error al cambiar el estado del mecánico.", "danger")
        return redirect(url_for("mechanics.index"))


@mechanic_bp.route("/<int:mechanic_id>/badge")
@login_required
def badge(mechanic_id):
    active_site_id = _get_active_site_id()
    mechanic = _get_mechanic_for_active_site_or_404(mechanic_id, active_site_id)
    return render_template("mechanics/badge.html", mechanic=mechanic)


@mechanic_bp.route("/<int:mechanic_id>/badge.pdf", methods=["GET"])
@login_required
def mechanic_badge_pdf(mechanic_id: int):
    active_site_id = _get_active_site_id()
    mechanic = _get_mechanic_for_active_site_or_404(mechanic_id, active_site_id)

    pdf_bytes = build_mechanic_badge_pdf(mechanic)

    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f'inline; filename="gafete_{mechanic.code}.pdf"'
    return response