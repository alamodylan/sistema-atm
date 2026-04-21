from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import db
from app.models.article import Article
from app.models.transfer import Transfer
from app.models.transfer_request import TransferRequest
from app.models.transfer_request_line import TransferRequestLine
from app.models.user_warehouse_access import UserWarehouseAccess
from app.models.warehouse import Warehouse
from app.services.transfer_service import (
    TransferServiceError,
    add_transfer_request_line,
    create_transfer_draft_from_request,
    create_transfer_request,
    finalize_transfer_request_review,
    get_request_line_stock_context,
    receive_transfer,
    remove_transfer_request_line,
    review_transfer_request_line,
    send_transfer,
    send_transfer_request,
    send_transfer_request_to_warehouse,
    update_transfer_request_line_quantity,
)

transfer_bp = Blueprint(
    "transfers",
    __name__,
    url_prefix="/transfers",
)


def _get_active_site_id() -> int | None:
    active_site_id = session.get("active_site_id")
    try:
        return int(active_site_id) if active_site_id else None
    except (TypeError, ValueError):
        return None


def _get_user_accessible_warehouses():
    if current_user.role and current_user.role.code == "SUPER_USUARIO":
        return (
            Warehouse.query
            .filter(Warehouse.is_active.is_(True))
            .order_by(Warehouse.name.asc())
            .all()
        )

    return (
        Warehouse.query
        .join(UserWarehouseAccess, UserWarehouseAccess.warehouse_id == Warehouse.id)
        .filter(
            UserWarehouseAccess.user_id == current_user.id,
            Warehouse.is_active.is_(True),
        )
        .order_by(Warehouse.name.asc())
        .all()
    )


def _get_request_or_404(transfer_request_id: int) -> TransferRequest:
    return TransferRequest.query.get_or_404(transfer_request_id)


def _get_transfer_or_404(transfer_id: int) -> Transfer:
    return Transfer.query.get_or_404(transfer_id)


def _build_request_line_stock_map(request_obj: TransferRequest) -> dict[int, dict]:
    stock_map: dict[int, dict] = {}

    for line in request_obj.lines:
        stock_map[line.id] = get_request_line_stock_context(
            requesting_warehouse_id=request_obj.origin_warehouse_id,
            supplying_warehouse_id=request_obj.destination_warehouse_id,
            article_id=line.article_id,
        )

    return stock_map


def _parse_selected_lines_from_form():
    selected_lines: list[dict] = []

    line_ids = request.form.getlist("transfer_request_line_id")
    for raw_line_id in line_ids:
        raw_line_id = (raw_line_id or "").strip()
        if not raw_line_id:
            continue

        qty_key = f"quantity_sent_{raw_line_id}"
        raw_qty = (request.form.get(qty_key) or "").strip()

        if not raw_qty:
            continue

        selected_lines.append(
            {
                "transfer_request_line_id": int(raw_line_id),
                "quantity_sent": raw_qty,
            }
        )

    return selected_lines


def _redirect_after_request_action(transfer_request_id: int):
    referrer = request.referrer or ""
    if "/dashboard/jefatura" in referrer:
        return redirect(url_for("dashboard.manager_dashboard"))
    return redirect(
        url_for("transfers.detail_request", transfer_request_id=transfer_request_id)
    )


@transfer_bp.route("/", methods=["GET"])
@login_required
def index():
    active_site_id = _get_active_site_id()

    request_query = TransferRequest.query
    transfer_query = Transfer.query

    if active_site_id:
        request_query = request_query.filter(
            (TransferRequest.origin_site_id == active_site_id)
            | (TransferRequest.destination_site_id == active_site_id)
        )
        transfer_query = transfer_query.filter(
            (Transfer.origin_site_id == active_site_id)
            | (Transfer.destination_site_id == active_site_id)
        )

    transfer_requests = (
        request_query
        .order_by(TransferRequest.created_at.desc(), TransferRequest.id.desc())
        .all()
    )

    transfers = (
        transfer_query
        .order_by(Transfer.created_at.desc(), Transfer.id.desc())
        .all()
    )

    return render_template(
        "transfers/index.html",
        transfer_requests=transfer_requests,
        transfers=transfers,
        active_site_id=active_site_id,
    )


@transfer_bp.route("/requests/create", methods=["GET", "POST"])
@login_required
def create_request():
    accessible_warehouses = _get_user_accessible_warehouses()
    supplying_warehouses = (
        Warehouse.query
        .filter(Warehouse.is_active.is_(True))
        .order_by(Warehouse.name.asc())
        .all()
    )
    articles = (
        Article.query
        .order_by(Article.code.asc(), Article.name.asc())
        .all()
    )

    if request.method == "POST":
        request_obj = None

        try:
            raw_origin_warehouse_id = request.form.get("origin_warehouse_id")
            raw_destination_warehouse_id = request.form.get("destination_warehouse_id")

            if not raw_origin_warehouse_id or not str(raw_origin_warehouse_id).strip():
                raise TransferServiceError("Debe seleccionar la bodega que solicita.")

            if not raw_destination_warehouse_id or not str(raw_destination_warehouse_id).strip():
                raise TransferServiceError("Debe seleccionar la bodega a la que se solicita.")

            origin_warehouse_id = int(raw_origin_warehouse_id)
            destination_warehouse_id = int(raw_destination_warehouse_id)
            priority = (request.form.get("priority") or "NORMAL").strip().upper()
            notes = (request.form.get("notes") or "").strip() or None

            article_ids = request.form.getlist("article_id[]")
            quantities = request.form.getlist("quantity_requested[]")
            line_notes = request.form.getlist("line_notes[]")

            valid_lines = []
            for idx, raw_article_id in enumerate(article_ids):
                raw_article_id = (raw_article_id or "").strip()
                raw_quantity = (quantities[idx] if idx < len(quantities) else "").strip()
                raw_note = (line_notes[idx] if idx < len(line_notes) else "").strip() or None

                if not raw_article_id and not raw_quantity:
                    continue

                if not raw_article_id:
                    raise TransferServiceError("Falta seleccionar el artículo en una de las líneas.")

                if not raw_quantity:
                    raise TransferServiceError("Falta la cantidad en una de las líneas.")

                valid_lines.append(
                    {
                        "article_id": int(raw_article_id),
                        "quantity_requested": raw_quantity,
                        "notes": raw_note,
                    }
                )

            if not valid_lines:
                raise TransferServiceError("Debe agregar al menos una línea de artículos.")

            current_app.logger.warning(
                "[TRANSFER CREATE][START] user_id=%s username=%s role=%s origin_warehouse_id=%s "
                "destination_warehouse_id=%s priority=%s valid_lines=%s accessible_warehouse_ids=%s",
                current_user.id,
                getattr(current_user, "username", None),
                getattr(getattr(current_user, "role", None), "code", None),
                origin_warehouse_id,
                destination_warehouse_id,
                priority,
                valid_lines,
                [w.id for w in accessible_warehouses],
            )

            request_obj = create_transfer_request(
                requested_by_user_id=current_user.id,
                origin_warehouse_id=origin_warehouse_id,
                destination_warehouse_id=destination_warehouse_id,
                priority=priority,
                notes=notes,
                commit=False,
            )

            current_app.logger.warning(
                "[TRANSFER CREATE][HEADER OK] request_id=%s number=%s",
                request_obj.id,
                request_obj.number,
            )

            db.session.flush()

            for line in valid_lines:
                current_app.logger.warning(
                    "[TRANSFER CREATE][ADDING LINE] request_id=%s article_id=%s quantity_requested=%s notes=%s",
                    request_obj.id,
                    line["article_id"],
                    line["quantity_requested"],
                    line["notes"],
                )

                add_transfer_request_line(
                    transfer_request_id=request_obj.id,
                    article_id=line["article_id"],
                    quantity_requested=line["quantity_requested"],
                    notes=line["notes"],
                    performed_by_user_id=current_user.id,
                    commit=False,
                )

            db.session.commit()

            current_app.logger.warning(
                "[TRANSFER CREATE][SUCCESS] request_id=%s number=%s",
                request_obj.id,
                request_obj.number,
            )

            flash("Solicitud de traslado creada correctamente.", "success")
            return redirect(
                url_for(
                    "transfers.detail_request",
                    transfer_request_id=request_obj.id,
                )
            )

        except TransferServiceError as exc:
            db.session.rollback()
            current_app.logger.warning(
                "[TRANSFER CREATE][BUSINESS ERROR] user_id=%s username=%s role=%s form=%s error=%s",
                getattr(current_user, "id", None),
                getattr(current_user, "username", None),
                getattr(getattr(current_user, "role", None), "code", None),
                request.form.to_dict(flat=False),
                str(exc),
            )
            flash(str(exc), "danger")

        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception(
                "[TRANSFER CREATE][UNEXPECTED ERROR] user_id=%s username=%s role=%s form=%s request_id=%s",
                getattr(current_user, "id", None),
                getattr(current_user, "username", None),
                getattr(getattr(current_user, "role", None), "code", None),
                request.form.to_dict(flat=False),
                getattr(request_obj, "id", None),
            )
            flash(f"No se pudo crear la solicitud de traslado: {exc}", "danger")

    return render_template(
        "transfers/create_request.html",
        accessible_warehouses=accessible_warehouses,
        supplying_warehouses=supplying_warehouses,
        articles=articles,
    )


@transfer_bp.route("/requests/<int:transfer_request_id>", methods=["GET"])
@login_required
def detail_request(transfer_request_id: int):
    request_obj = _get_request_or_404(transfer_request_id)
    stock_map = _build_request_line_stock_map(request_obj)
    active_site_id = _get_active_site_id()

    articles = (
        Article.query
        .order_by(Article.code.asc(), Article.name.asc())
        .all()
    )

    is_destination_site_view = (
        active_site_id is not None
        and request_obj.destination_site_id == active_site_id
    )

    can_operate_as_supplying_warehouse = (
        is_destination_site_view
        and request_obj.sent_to_warehouse_at is not None
        and request_obj.status in {"APROBADA", "ATENDIDA_PARCIAL"}
    )

    visible_lines = list(request_obj.lines)

    if can_operate_as_supplying_warehouse:
        visible_lines = []
        for line in request_obj.lines:
            manager_status = (line.manager_review_status or "").strip().upper()
            qty_approved = line.quantity_approved or 0
            qty_attended = line.quantity_attended or 0
            qty_pending = qty_approved - qty_attended

            if manager_status != "APROBADA":
                continue
            if qty_approved <= 0:
                continue
            if qty_pending <= 0:
                continue

            line.pending_transfer_quantity = qty_pending
            visible_lines.append(line)

    return render_template(
        "transfers/detail_request.html",
        transfer_request=request_obj,
        stock_map=stock_map,
        articles=articles,
        visible_lines=visible_lines,
        can_operate_as_supplying_warehouse=can_operate_as_supplying_warehouse,
    )


@transfer_bp.route("/requests/<int:transfer_request_id>/lines/add", methods=["POST"])
@login_required
def add_request_line(transfer_request_id: int):
    try:
        article_id = int(request.form.get("article_id"))
        quantity_requested = request.form.get("quantity_requested")
        notes = (request.form.get("notes") or "").strip() or None

        add_transfer_request_line(
            transfer_request_id=transfer_request_id,
            article_id=article_id,
            quantity_requested=quantity_requested,
            notes=notes,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Línea agregada correctamente.", "success")

    except TransferServiceError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    except Exception:
        db.session.rollback()
        flash("No se pudo agregar la línea.", "danger")

    return redirect(
        url_for("transfers.detail_request", transfer_request_id=transfer_request_id)
    )


@transfer_bp.route("/request-lines/<int:transfer_request_line_id>/update", methods=["POST"])
@login_required
def update_request_line(transfer_request_line_id: int):
    line = TransferRequestLine.query.get_or_404(transfer_request_line_id)

    try:
        quantity_requested = request.form.get("quantity_requested")

        update_transfer_request_line_quantity(
            transfer_request_line_id=transfer_request_line_id,
            quantity_requested=quantity_requested,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Cantidad solicitada actualizada correctamente.", "success")

    except TransferServiceError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    except Exception:
        db.session.rollback()
        flash("No se pudo actualizar la línea.", "danger")

    return redirect(
        url_for("transfers.detail_request", transfer_request_id=line.transfer_request_id)
    )


@transfer_bp.route("/request-lines/<int:transfer_request_line_id>/delete", methods=["POST"])
@login_required
def delete_request_line(transfer_request_line_id: int):
    line = TransferRequestLine.query.get_or_404(transfer_request_line_id)
    transfer_request_id = line.transfer_request_id

    try:
        remove_transfer_request_line(
            transfer_request_line_id=transfer_request_line_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Línea eliminada correctamente.", "success")

    except TransferServiceError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    except Exception:
        db.session.rollback()
        flash("No se pudo eliminar la línea.", "danger")

    return redirect(
        url_for("transfers.detail_request", transfer_request_id=transfer_request_id)
    )


@transfer_bp.route("/requests/<int:transfer_request_id>/send", methods=["POST"])
@login_required
def submit_request(transfer_request_id: int):
    try:
        send_transfer_request(
            transfer_request_id=transfer_request_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Solicitud enviada correctamente.", "success")

    except TransferServiceError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    except Exception:
        db.session.rollback()
        flash("No se pudo enviar la solicitud.", "danger")

    return redirect(
        url_for("transfers.detail_request", transfer_request_id=transfer_request_id)
    )


@transfer_bp.route("/request-lines/<int:transfer_request_line_id>/review", methods=["POST"])
@login_required
def review_request_line(transfer_request_line_id: int):
    line = TransferRequestLine.query.get_or_404(transfer_request_line_id)

    try:
        action = (request.form.get("action") or "").strip().upper()
        quantity_approved = request.form.get("quantity_approved")
        rejection_reason = (request.form.get("rejection_reason") or "").strip() or None

        kwargs = {
            "transfer_request_line_id": transfer_request_line_id,
            "performed_by_user_id": current_user.id,
            "action": action,
            "rejection_reason": rejection_reason,
            "commit": True,
        }

        if action == "APROBAR":
            kwargs["quantity_approved"] = quantity_approved

        review_transfer_request_line(**kwargs)
        flash("Línea revisada correctamente.", "success")

    except TransferServiceError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    except Exception:
        db.session.rollback()
        flash("No se pudo revisar la línea.", "danger")

    return _redirect_after_request_action(line.transfer_request_id)


@transfer_bp.route("/requests/<int:transfer_request_id>/finalize-review", methods=["POST"])
@login_required
def finalize_request_review(transfer_request_id: int):
    try:
        approval_note = (request.form.get("approval_note") or "").strip() or None

        finalize_transfer_request_review(
            transfer_request_id=transfer_request_id,
            performed_by_user_id=current_user.id,
            approval_note=approval_note,
            commit=True,
        )
        flash("Revisión de jefatura finalizada correctamente.", "success")

    except TransferServiceError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    except Exception:
        db.session.rollback()
        flash("No se pudo finalizar la revisión.", "danger")

    return _redirect_after_request_action(transfer_request_id)


@transfer_bp.route("/requests/<int:transfer_request_id>/send-to-warehouse", methods=["POST"])
@login_required
def submit_request_to_warehouse(transfer_request_id: int):
    try:
        send_transfer_request_to_warehouse(
            transfer_request_id=transfer_request_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Solicitud enviada a bodega correctamente.", "success")

    except TransferServiceError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    except Exception:
        db.session.rollback()
        flash("No se pudo enviar la solicitud a bodega.", "danger")

    return _redirect_after_request_action(transfer_request_id)


@transfer_bp.route("/requests/<int:transfer_request_id>/create-transfer-draft", methods=["POST"])
@login_required
def create_transfer_draft(transfer_request_id: int):
    try:
        selected_lines = _parse_selected_lines_from_form()
        notes = (request.form.get("notes") or "").strip() or None

        current_app.logger.warning(
            "[TRANSFER DRAFT][START] request_id=%s user_id=%s username=%s selected_lines=%s notes=%s",
            transfer_request_id,
            current_user.id,
            getattr(current_user, "username", None),
            selected_lines,
            notes,
        )

        transfer = create_transfer_draft_from_request(
            transfer_request_id=transfer_request_id,
            created_by_user_id=current_user.id,
            selected_lines=selected_lines,
            notes=notes,
            commit=True,
        )

        current_app.logger.warning(
            "[TRANSFER DRAFT][SUCCESS] request_id=%s transfer_id=%s number=%s",
            transfer_request_id,
            transfer.id,
            transfer.number,
        )

        flash("Traslado borrador creado correctamente.", "success")

        return redirect(
            url_for("transfers.detail_transfer", transfer_id=transfer.id)
        )

    except TransferServiceError as exc:
        db.session.rollback()
        current_app.logger.warning(
            "[TRANSFER DRAFT][BUSINESS ERROR] request_id=%s user_id=%s username=%s form=%s error=%s",
            transfer_request_id,
            getattr(current_user, "id", None),
            getattr(current_user, "username", None),
            request.form.to_dict(flat=False),
            str(exc),
        )
        flash(str(exc), "danger")

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(
            "[TRANSFER DRAFT][UNEXPECTED ERROR] request_id=%s user_id=%s username=%s form=%s",
            transfer_request_id,
            getattr(current_user, "id", None),
            getattr(current_user, "username", None),
            request.form.to_dict(flat=False),
        )
        flash(f"No se pudo crear el traslado borrador: {exc}", "danger")

    return redirect(
        url_for("transfers.detail_request", transfer_request_id=transfer_request_id)
    )


@transfer_bp.route("/transfers/<int:transfer_id>", methods=["GET"])
@login_required
def detail_transfer(transfer_id: int):
    transfer = _get_transfer_or_404(transfer_id)

    from app.services.transfer_service import _get_available_quantity

    stock_map = {}
    can_send = True

    for line in transfer.lines:
        available = _get_available_quantity(
            transfer.origin_warehouse_id,
            line.article_id
        )

        stock_map[line.id] = available

        if line.quantity_sent > available:
            can_send = False

    return render_template(
        "transfers/detail_transfer.html",
        transfer=transfer,
        stock_map=stock_map,
        can_send=can_send,
    )


@transfer_bp.route("/transfers/<int:transfer_id>/send", methods=["POST"])
@login_required
def submit_transfer(transfer_id: int):
    try:
        send_transfer(
            transfer_id=transfer_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Traslado enviado correctamente.", "success")

    except TransferServiceError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    except Exception:
        db.session.rollback()
        flash("No se pudo enviar el traslado.", "danger")

    return redirect(
        url_for("transfers.detail_transfer", transfer_id=transfer_id)
    )


@transfer_bp.route("/transfers/<int:transfer_id>/receive", methods=["POST"])
@login_required
def complete_transfer_receipt(transfer_id: int):
    transfer = _get_transfer_or_404(transfer_id)

    try:
        received_lines: list[dict] = []

        for line in transfer.lines:
            qty_key = f"quantity_received_{line.id}"
            raw_qty = (request.form.get(qty_key) or "").strip()
            if not raw_qty:
                continue

            received_lines.append(
                {
                    "transfer_line_id": line.id,
                    "quantity_received": raw_qty,
                }
            )

        receive_transfer(
            transfer_id=transfer_id,
            received_by_user_id=current_user.id,
            received_lines=received_lines or None,
            commit=True,
        )
        flash("Traslado recibido correctamente.", "success")

    except TransferServiceError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    except Exception:
        db.session.rollback()
        flash("No se pudo recibir el traslado.", "danger")

    return redirect(
        url_for("transfers.detail_transfer", transfer_id=transfer_id)
    )