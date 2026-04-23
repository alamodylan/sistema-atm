import os
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.models.warehouse import Warehouse
from app.models.waste_act import WasteAct
from app.models.waste_act_line import WasteActLine
from app.services.waste_service import (
    WasteServiceError,
    add_line_to_waste_act,
    change_waste_act_status,
    create_waste_act,
    get_waste_candidates,
    set_signed_pdf_path,
)

waste_bp = Blueprint("waste", __name__)


def _get_active_site_id() -> int:
    active_site_id = session.get("active_site_id")
    if not active_site_id:
        raise ValueError("Debe seleccionar un predio activo para continuar.")
    return int(active_site_id)


def _get_active_site_warehouses(site_id: int):
    return (
        Warehouse.query.filter(
            Warehouse.site_id == site_id,
            Warehouse.is_active.is_(True),
        )
        .order_by(Warehouse.name.asc(), Warehouse.id.asc())
        .all()
    )


def _get_waste_act_for_active_site_or_error(waste_act_id: int, active_site_id: int) -> WasteAct:
    waste_act = WasteAct.query.filter(
        WasteAct.id == waste_act_id,
        WasteAct.site_id == active_site_id,
    ).first()

    if not waste_act:
        raise ValueError("El acta de desecho no existe o no pertenece al predio activo.")

    return waste_act


def _build_signed_pdf_storage_path(waste_act: WasteAct, original_filename: str) -> tuple[str, str]:
    safe_name = secure_filename(original_filename or "acta_firmada.pdf")
    if not safe_name.lower().endswith(".pdf"):
        safe_name = f"{safe_name}.pdf"

    folder = os.path.join(
        current_app.instance_path,
        "uploads",
        "waste_acts",
        str(waste_act.id),
    )
    os.makedirs(folder, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"acta_desecho_firmada_{waste_act.id}_{timestamp}.pdf"
    absolute_path = os.path.join(folder, filename)

    return absolute_path, filename


@waste_bp.route("/", methods=["GET"])
@login_required
def list_waste_acts():
    status = (request.args.get("status") or "").strip()

    try:
        active_site_id = _get_active_site_id()

        query = WasteAct.query.filter(WasteAct.site_id == active_site_id)

        if status:
            query = query.filter(WasteAct.status == status)

        waste_acts = query.order_by(WasteAct.created_at.desc()).all()

        return render_template(
            "waste/index.html",
            waste_acts=waste_acts,
            status=status,
        )

    except Exception:
        flash("Error al cargar las actas.", "danger")

    return render_template("waste/index.html", waste_acts=[], status=status)


@waste_bp.route("/create", methods=["GET"])
@login_required
def create_waste_act_page():
    try:
        active_site_id = _get_active_site_id()
        warehouses = _get_active_site_warehouses(active_site_id)

        return render_template(
            "waste/create.html",
            warehouses=warehouses,
        )

    except Exception:
        flash("Error al cargar pantalla de creación.", "danger")

    return redirect(url_for("waste.list_waste_acts"))


@waste_bp.route("/", methods=["POST"])
@login_required
def create_waste_act_action():
    try:
        active_site_id = _get_active_site_id()

        warehouse_id = request.form.get("warehouse_id")
        date_from = request.form.get("date_from")
        date_to = request.form.get("date_to")
        notes = request.form.get("notes")

        warehouse = Warehouse.query.filter(
            Warehouse.id == int(warehouse_id),
            Warehouse.site_id == active_site_id,
            Warehouse.is_active.is_(True),
        ).first()

        if not warehouse:
            raise ValueError("Bodega inválida.")

        waste_act = create_waste_act(
            site_id=active_site_id,
            warehouse_id=warehouse.id,
            date_from=date_from,
            date_to=date_to,
            created_by_user_id=current_user.id,
            notes=notes,
            commit=True,
        )

        flash(f"Acta {waste_act.number} creada.", "success")
        return redirect(url_for("waste.waste_candidates", waste_act_id=waste_act.id))

    except Exception as exc:
        flash(str(exc), "danger")

    return redirect(url_for("waste.create_waste_act_page"))


@waste_bp.route("/<int:waste_act_id>/candidates", methods=["GET"])
@login_required
def waste_candidates(waste_act_id: int):
    try:
        active_site_id = _get_active_site_id()
        waste_act = _get_waste_act_for_active_site_or_error(waste_act_id, active_site_id)

        candidates = get_waste_candidates(
            date_from=waste_act.date_from,
            date_to=waste_act.date_to,
            site_id=waste_act.site_id,
            warehouse_id=waste_act.warehouse_id,
        )

        added_lines = (
            waste_act.lines
            .order_by(WasteActLine.created_at.desc())
            .all()
        )

        return render_template(
            "waste/candidates.html",
            waste_act=waste_act,
            candidates=candidates,
            added_lines=added_lines,
        )

    except Exception as exc:
        flash(str(exc), "danger")

    return redirect(url_for("waste.list_waste_acts"))


@waste_bp.route("/<int:waste_act_id>/lines", methods=["POST"])
@login_required
def add_waste_act_line(waste_act_id: int):
    try:
        active_site_id = _get_active_site_id()
        waste_act = _get_waste_act_for_active_site_or_error(waste_act_id, active_site_id)

        disposal_type = (request.form.get("disposal_type") or "").strip().upper()

        if disposal_type not in {"PENDIENTE", "CONFIRMADO", "CONSUMIBLE"}:
            raise ValueError("Tipo de disposición inválido.")

        add_line_to_waste_act(
            waste_act_id=waste_act.id,
            work_order_line_id=int(request.form.get("work_order_line_id")),
            quantity=request.form.get("quantity"),
            disposal_type=disposal_type,
            notes=request.form.get("notes"),
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Línea agregada.", "success")

    except Exception as exc:
        flash(str(exc), "danger")

    return redirect(url_for("waste.waste_candidates", waste_act_id=waste_act_id))


@waste_bp.route("/<int:waste_act_id>/signed-pdf", methods=["POST"])
@login_required
def upload_signed_pdf(waste_act_id: int):
    try:
        active_site_id = _get_active_site_id()
        waste_act = _get_waste_act_for_active_site_or_error(waste_act_id, active_site_id)

        if waste_act.status not in ["REGISTRADA", "IMPRESA"]:
            raise ValueError("Solo se puede subir el PDF firmado a un acta REGISTRADA o IMPRESA.")

        uploaded_file = request.files.get("signed_pdf")
        if not uploaded_file or not uploaded_file.filename:
            raise ValueError("Debe seleccionar un archivo PDF.")

        filename = uploaded_file.filename.strip()
        if not filename.lower().endswith(".pdf"):
            raise ValueError("El archivo debe estar en formato PDF.")

        absolute_path, _ = _build_signed_pdf_storage_path(waste_act, filename)
        uploaded_file.save(absolute_path)

        set_signed_pdf_path(
            waste_act_id=waste_act.id,
            signed_pdf_path=absolute_path,
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("PDF firmado cargado correctamente.", "success")

    except (WasteServiceError, ValueError) as exc:
        flash(str(exc), "danger")

    except Exception:
        flash("Error al subir el PDF firmado.", "danger")

    return redirect(url_for("waste.waste_candidates", waste_act_id=waste_act_id))


@waste_bp.route("/<int:waste_act_id>/signed-pdf/view", methods=["GET"])
@login_required
def view_signed_pdf(waste_act_id: int):
    try:
        active_site_id = _get_active_site_id()
        waste_act = _get_waste_act_for_active_site_or_error(waste_act_id, active_site_id)

        if not waste_act.signed_pdf_path:
            raise ValueError("Esta acta no tiene PDF firmado cargado.")

        if not os.path.exists(waste_act.signed_pdf_path):
            raise ValueError("El archivo PDF firmado no fue encontrado.")

        return send_file(
            waste_act.signed_pdf_path,
            mimetype="application/pdf",
            as_attachment=False,
            download_name=os.path.basename(waste_act.signed_pdf_path),
        )

    except Exception as exc:
        flash(str(exc), "danger")

    return redirect(url_for("waste.waste_candidates", waste_act_id=waste_act_id))


@waste_bp.route("/<int:waste_act_id>/status", methods=["POST"])
@login_required
def update_waste_act_status(waste_act_id: int):
    try:
        active_site_id = _get_active_site_id()
        waste_act = _get_waste_act_for_active_site_or_error(waste_act_id, active_site_id)

        new_status = request.form.get("new_status")

        change_waste_act_status(
            waste_act_id=waste_act.id,
            new_status=new_status,
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Estado actualizado.", "success")

    except Exception as exc:
        flash(str(exc), "danger")

    return redirect(url_for("waste.waste_candidates", waste_act_id=waste_act_id))


@waste_bp.route("/<int:waste_act_id>/cancel", methods=["POST"])
@login_required
def cancel_waste_act(waste_act_id: int):
    try:
        active_site_id = _get_active_site_id()
        waste_act = _get_waste_act_for_active_site_or_error(waste_act_id, active_site_id)

        change_waste_act_status(
            waste_act_id=waste_act.id,
            new_status="CANCELADA",
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Acta anulada correctamente. Las líneas quedaron liberadas para futuras actas.", "warning")

    except Exception as exc:
        flash(str(exc), "danger")

    return redirect(url_for("waste.list_waste_acts"))


@waste_bp.route("/<int:waste_act_id>/print", methods=["GET"])
@login_required
def print_waste_act(waste_act_id: int):
    try:
        active_site_id = _get_active_site_id()
        waste_act = _get_waste_act_for_active_site_or_error(waste_act_id, active_site_id)

        added_lines = (
            waste_act.lines
            .order_by(WasteActLine.created_at.asc())
            .all()
        )

        return render_template(
            "waste/print.html",
            waste_act=waste_act,
            added_lines=added_lines,
        )

    except Exception:
        flash("Error al imprimir.", "danger")

    return redirect(url_for("waste.list_waste_acts"))