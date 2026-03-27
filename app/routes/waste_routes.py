from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models.waste_act import WasteAct
from app.services.waste_service import (
    WasteServiceError,
    add_line_to_waste_act,
    change_waste_act_status,
    create_waste_act,
    get_waste_candidates,
)

waste_bp = Blueprint("waste", __name__)


# =========================================================
# LISTADO DE ACTAS DE DESECHO
# =========================================================
@waste_bp.route("/", methods=["GET"])
@login_required
def list_waste_acts():
    status = (request.args.get("status") or "").strip()

    try:
        query = WasteAct.query

        if status:
            query = query.filter(WasteAct.status == status)

        waste_acts = query.order_by(WasteAct.created_at.desc()).all()

        return render_template(
            "waste/index.html",
            title="Actas de desecho",
            subtitle="Consulte actas generadas y su estado actual.",
            waste_acts=waste_acts,
            status=status,
        )

    except Exception:
        flash("Error al cargar las actas de desecho.", "danger")
        return render_template(
            "waste/index.html",
            title="Actas de desecho",
            subtitle="Consulte actas generadas y su estado actual.",
            waste_acts=[],
            status=status,
        )


# =========================================================
# PANTALLA CREAR ACTA
# =========================================================
@waste_bp.route("/create", methods=["GET"])
@login_required
def create_waste_act_page():
    return render_template(
        "waste/create.html",
        title="Nueva Acta de Desecho",
        subtitle="Defina el rango de fechas y filtros para consultar candidatos.",
    )


# =========================================================
# CREAR ACTA
# =========================================================
@waste_bp.route("/", methods=["POST"])
@login_required
def create_waste_act_action():
    try:
        number = (request.form.get("number") or "").strip()
        site_id = request.form.get("site_id")
        warehouse_id = request.form.get("warehouse_id")
        date_from = request.form.get("date_from")
        date_to = request.form.get("date_to")
        notes = request.form.get("notes")

        if not number:
            raise ValueError("El número del acta es obligatorio.")

        if not site_id:
            raise ValueError("El predio es obligatorio.")

        if not warehouse_id:
            raise ValueError("La bodega es obligatoria.")

        if not date_from or not date_to:
            raise ValueError("Debe indicar el rango de fechas.")

        waste_act = create_waste_act(
            number=number,
            site_id=int(site_id),
            warehouse_id=int(warehouse_id),
            date_from=date_from,
            date_to=date_to,
            created_by_user_id=current_user.id,
            notes=notes,
            commit=True,
        )

        flash(f"Acta de desecho {waste_act.number} creada correctamente.", "success")
        return redirect(url_for("waste.waste_candidates", waste_act_id=waste_act.id))

    except (WasteServiceError, ValueError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("waste.create_waste_act_page"))

    except Exception:
        flash("Error interno al crear el acta de desecho.", "danger")
        return redirect(url_for("waste.create_waste_act_page"))


# =========================================================
# CANDIDATOS PARA ACTA
# =========================================================
@waste_bp.route("/<int:waste_act_id>/candidates", methods=["GET"])
@login_required
def waste_candidates(waste_act_id: int):
    try:
        waste_act = WasteAct.query.get(waste_act_id)

        if not waste_act:
            raise ValueError("El acta de desecho no existe.")

        candidates = get_waste_candidates(
            date_from=waste_act.date_from,
            date_to=waste_act.date_to,
            site_id=waste_act.site_id,
            warehouse_id=waste_act.warehouse_id,
        )

        return render_template(
            "waste/candidates.html",
            title="Candidatos para acta de desecho",
            subtitle="Seleccione cuáles líneas realmente estarán incluidas en el acta.",
            waste_act=waste_act,
            candidates=candidates,
        )

    except (WasteServiceError, ValueError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("waste.list_waste_acts"))

    except Exception:
        flash("Error al cargar los candidatos del acta.", "danger")
        return redirect(url_for("waste.list_waste_acts"))


# =========================================================
# AGREGAR LÍNEA AL ACTA
# =========================================================
@waste_bp.route("/<int:waste_act_id>/lines", methods=["POST"])
@login_required
def add_waste_act_line(waste_act_id: int):
    try:
        work_order_line_id = request.form.get("work_order_line_id")
        quantity = request.form.get("quantity")
        confirmed_for_disposal = request.form.get("confirmed_for_disposal")
        notes = request.form.get("notes")

        if not work_order_line_id:
            raise ValueError("Debe seleccionar una línea de OT.")

        if not quantity:
            raise ValueError("Debe indicar la cantidad.")

        add_line_to_waste_act(
            waste_act_id=waste_act_id,
            work_order_line_id=int(work_order_line_id),
            quantity=quantity,
            confirmed_for_disposal=str(confirmed_for_disposal).lower() in {"1", "true", "on", "yes", "si", "sí"},
            notes=notes,
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Línea agregada correctamente al acta de desecho.", "success")

    except (WasteServiceError, ValueError) as exc:
        flash(str(exc), "danger")

    except Exception:
        flash("Error interno al agregar la línea al acta.", "danger")

    return redirect(url_for("waste.waste_candidates", waste_act_id=waste_act_id))


# =========================================================
# CAMBIAR ESTADO DEL ACTA
# =========================================================
@waste_bp.route("/<int:waste_act_id>/status", methods=["POST"])
@login_required
def update_waste_act_status(waste_act_id: int):
    try:
        new_status = (request.form.get("new_status") or "").strip().upper()

        if not new_status:
            raise ValueError("Debe indicar el nuevo estado del acta.")

        change_waste_act_status(
            waste_act_id=waste_act_id,
            new_status=new_status,
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Estado del acta actualizado correctamente.", "success")

    except (WasteServiceError, ValueError) as exc:
        flash(str(exc), "danger")

    except Exception:
        flash("Error interno al actualizar el estado del acta.", "danger")

    return redirect(url_for("waste.waste_candidates", waste_act_id=waste_act_id))


# =========================================================
# IMPRESIÓN ACTA
# =========================================================
@waste_bp.route("/<int:waste_act_id>/print", methods=["GET"])
@login_required
def print_waste_act(waste_act_id: int):
    try:
        waste_act = WasteAct.query.get(waste_act_id)

        if not waste_act:
            raise ValueError("El acta de desecho no existe.")

        return render_template(
            "waste/print.html",
            waste_act=waste_act,
        )

    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("waste.list_waste_acts"))

    except Exception:
        flash("Error al generar la impresión del acta.", "danger")
        return redirect(url_for("waste.list_waste_acts"))