from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required
from flask import make_response
from app.services.badge_pdf_service import build_mechanic_badge_pdf

from app.extensions import db
from app.models.mechanic import Mechanic

mechanic_bp = Blueprint("mechanics", __name__, url_prefix="/mechanics")


@mechanic_bp.route("/")
@login_required
def index():
    active_site_id = session.get("active_site_id")

    mechanics = Mechanic.query.filter_by(
        site_id=active_site_id
    ).order_by(Mechanic.name.asc()).all()

    return render_template("mechanics/index.html", mechanics=mechanics)


@mechanic_bp.route("/create", methods=["POST"])
@login_required
def create():
    active_site_id = session.get("active_site_id")

    name = request.form.get("name")
    code = request.form.get("code")

    if not name or not code:
        flash("Nombre y código son obligatorios", "danger")
        return redirect(url_for("mechanics.index"))

    mechanic = Mechanic(
        site_id=active_site_id,
        name=name,
        code=code,
    )

    db.session.add(mechanic)
    db.session.commit()

    return redirect(url_for("mechanics.index"))


@mechanic_bp.route("/<int:mechanic_id>")
@login_required
def detail(mechanic_id):
    mechanic = Mechanic.query.get_or_404(mechanic_id)
    return render_template("mechanics/detail.html", mechanic=mechanic)


@mechanic_bp.route("/<int:mechanic_id>/toggle")
@login_required
def toggle(mechanic_id):
    mechanic = Mechanic.query.get_or_404(mechanic_id)

    mechanic.is_active = not mechanic.is_active
    db.session.commit()

    return redirect(url_for("mechanics.index"))


@mechanic_bp.route("/<int:mechanic_id>/badge")
@login_required
def badge(mechanic_id):
    mechanic = Mechanic.query.get_or_404(mechanic_id)
    return render_template("mechanics/badge.html", mechanic=mechanic)

@mechanic_bp.route("/<int:mechanic_id>/badge.pdf", methods=["GET"])
@login_required
def mechanic_badge_pdf(mechanic_id: int):
    mechanic = Mechanic.query.get_or_404(mechanic_id)

    pdf_bytes = build_mechanic_badge_pdf(mechanic)

    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f'inline; filename="gafete_{mechanic.code}.pdf"'
    return response