# routes/work_order_requests.py
from decimal import Decimal, InvalidOperation

from flask import Blueprint, flash, redirect, request, url_for
from flask_login import current_user, login_required
from app.models.work_order_request_line import WorkOrderRequestLine
from app.models.inventory import WarehouseStock
from datetime import datetime, UTC
from app.extensions import db
from app.models.tool_loan import ToolLoan
from app.services.inventory_service import add_stock, InventoryServiceError
from sqlalchemy.orm import joinedload
from app.models.article import Article
from app.models.work_order_request import WorkOrderRequest
from sqlalchemy.orm import joinedload, selectinload
from app.services.work_order_request_service import (
    WorkOrderRequestServiceError,
    add_request_line,
    attend_and_post_request_line,
    cancel_request_line,
    confirm_request_line_to_work_order,
    create_request,
    mark_request_line_loaned,
    mark_request_line_not_delivered,
    reject_request_line_by_management,
    send_request,
    send_request_to_warehouse,
    undo_manager_decision,
    update_request_line_requested_quantity,
    void_request_line,
)

work_order_request_bp = Blueprint("work_order_requests", __name__)


# =========================
# CREAR SOLICITUD
# =========================
@work_order_request_bp.route("/work-orders/<int:work_order_id>/requests", methods=["POST"])
@login_required
def create_request_action(work_order_id: int):
    try:
        create_request(
            work_order_id=work_order_id,
            requested_by_user_id=current_user.id,
            commit=True,
        )
        flash("Solicitud creada.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(url_for("work_orders.get_work_order", work_order_id=work_order_id))


# =========================
# AGREGAR LÍNEA
# =========================
@work_order_request_bp.route("/requests/<int:request_id>/lines", methods=["POST"])
@login_required
def add_request_line_action(request_id: int):
    try:
        article_id = request.form.get("article_id")
        quantity_raw = request.form.get("quantity")
        notes = request.form.get("notes")

        if not article_id or not quantity_raw:
            raise ValueError("Datos incompletos.")

        qty = Decimal(quantity_raw)

        add_request_line(
            request_id=request_id,
            article_id=int(article_id),
            quantity_requested=qty,
            notes=notes,
            commit=True,
        )

        flash("Línea agregada a la solicitud.", "success")

    except (WorkOrderRequestServiceError, ValueError, InvalidOperation) as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# MECÁNICO ENVÍA
# =========================
@work_order_request_bp.route("/requests/<int:request_id>/send", methods=["POST"])
@login_required
def send_request_action(request_id: int):
    try:
        send_request(
            request_id=request_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Solicitud enviada a jefatura.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# JEFATURA → ENVIAR A BODEGA
# =========================
@work_order_request_bp.route("/requests/<int:request_id>/send-to-warehouse", methods=["POST"])
@login_required
def send_request_to_warehouse_action(request_id: int):
    try:
        send_request_to_warehouse(
            request_id=request_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Solicitud enviada a bodega.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# CANCELAR LÍNEA
# =========================
@work_order_request_bp.route("/request-lines/<int:line_id>/cancel", methods=["POST"])
@login_required
def cancel_request_line_action(line_id: int):
    try:
        cancel_request_line(
            request_line_id=line_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Línea cancelada correctamente.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")

# =========================
# ANULAR LÍNEA DE SOLICITUD
# =========================
@work_order_request_bp.route(
    "/request-lines/<int:line_id>/void",
    methods=["POST"],
)
@login_required
def void_request_line_action(line_id: int):
    try:
        allowed_role_codes = {
            "ADMIN",
            "TALLER",
            "SUPER_USUARIO",
        }

        current_role_code = str(
            current_user.role_code or ""
        ).strip().upper()

        if current_role_code not in allowed_role_codes:
            flash(
                "Solo los usuarios Administrador y Taller "
                "pueden anular líneas de solicitudes.",
                "danger",
            )
            return redirect(request.referrer or "/")

        reason = (
            request.form.get("reason") or ""
        ).strip()

        void_request_line(
            request_line_id=line_id,
            reason=reason,
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash(
            "Línea de solicitud anulada correctamente.",
            "success",
        )

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    except Exception as exc:
        db.session.rollback()

        print(
            "[VOID REQUEST LINE ERROR] "
            f"line_id={line_id} "
            f"error={exc}"
        )

        flash(
            "No fue posible anular la línea de solicitud.",
            "danger",
        )

    return redirect(request.referrer or "/")
# =========================
# JEFATURA → APROBAR / AJUSTAR
# =========================
@work_order_request_bp.route("/request-lines/<int:line_id>/approve", methods=["POST"])
@login_required
def approve_request_line_action(line_id: int):
    try:
        line = (
            WorkOrderRequestLine.query
            .options(
                joinedload(WorkOrderRequestLine.article)
                    .joinedload(Article.unit),
                joinedload(WorkOrderRequestLine.work_order_request)
                    .joinedload(WorkOrderRequest.work_order),
            )
            .filter(WorkOrderRequestLine.id == line_id)
            .first_or_404()
        )

        qty = Decimal(request.form.get("quantity") or "0")

        stock = (
            WarehouseStock.query
            .filter(
                WarehouseStock.article_id == line.article_id,
                WarehouseStock.warehouse_id == line.work_order_request.work_order.warehouse_id,
            )
            .first()
        )

        available_qty = Decimal(str(stock.available_quantity if stock else 0))

        if qty <= 0:
            raise ValueError("La cantidad debe ser mayor a cero.")

        if qty > available_qty:
            raise ValueError("No se puede aprobar más que el stock disponible.")

        unit_code = line.article.unit.code if line.article and line.article.unit else ""

        if unit_code == "UND" and qty != qty.to_integral_value():
            raise ValueError(
                "Este artículo usa unidad UND, solo permite cantidades enteras."
            )

        update_request_line_requested_quantity(
            request_line_id=line_id,
            quantity_requested=qty,
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Cantidad aprobada/ajustada.", "success")

    except (WorkOrderRequestServiceError, InvalidOperation, ValueError) as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# JEFATURA → RECHAZAR
# =========================
@work_order_request_bp.route("/request-lines/<int:line_id>/reject", methods=["POST"])
@login_required
def reject_request_line_action(line_id: int):
    try:
        reject_request_line_by_management(
            request_line_id=line_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Línea rechazada.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# JEFATURA → DESHACER DECISIÓN
# =========================
@work_order_request_bp.route("/request-lines/<int:line_id>/undo-manager-decision", methods=["POST"])
@login_required
def undo_manager_decision_action(line_id: int):
    try:
        undo_manager_decision(
            request_line_id=line_id,
            performed_by_user_id=current_user.id,
            commit=True,
        )
        flash("Decisión de jefatura revertida.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# BODEGA → PREPARAR Y APLICAR SALIDA
# =========================
@work_order_request_bp.route(
    "/request-lines/<int:line_id>/attend",
    methods=["POST"],
)
@login_required
def attend_request_line_action(line_id: int):
    try:
        quantity_raw = (
            request.form.get("quantity")
            or ""
        ).strip()

        if not quantity_raw:
            raise ValueError(
                "Debe indicar la cantidad a preparar."
            )

        quantity = Decimal(quantity_raw)

        line, work_order_line = (
            attend_and_post_request_line(
                request_line_id=line_id,
                quantity=quantity,
                performed_by_user_id=current_user.id,
                commit=True,
            )
        )

        flash(
            (
                "Línea preparada, entregada y rebajada "
                "del inventario correctamente."
            ),
            "success",
        )

    except (
        WorkOrderRequestServiceError,
        InvalidOperation,
        ValueError,
    ) as exc:
        db.session.rollback()

        flash(
            str(exc),
            "danger",
        )

    except Exception as exc:
        db.session.rollback()

        print(
            "[ATTEND AND POST REQUEST LINE ERROR] "
            f"line_id={line_id} "
            f"{type(exc).__name__}: {exc}"
        )

        flash(
            "No fue posible preparar y aplicar "
            "la salida del artículo.",
            "danger",
        )

    return redirect(
        request.referrer or "/"
    )


# =========================
# BODEGA → PREPARAR PEDIDO COMPLETO
# =========================
@work_order_request_bp.route(
    "/requests/<int:request_id>/prepare-batch",
    methods=["POST"],
)
@login_required
def prepare_request_batch_action(request_id: int):
    try:
        request_obj = (
            WorkOrderRequest.query
            .options(
                selectinload(
                    WorkOrderRequest.lines
                ).joinedload(
                    WorkOrderRequestLine.article
                )
            )
            .filter(
                WorkOrderRequest.id == request_id
            )
            .with_for_update()
            .first()
        )

        if not request_obj:
            raise WorkOrderRequestServiceError(
                "La solicitud no existe."
            )

        if request_obj.request_status not in {
            "ENVIADA",
            "ATENDIDA",
        }:
            raise WorkOrderRequestServiceError(
                "La solicitud no está disponible para bodega."
            )

        if not request_obj.sent_to_warehouse_at:
            raise WorkOrderRequestServiceError(
                "La solicitud todavía no fue enviada a bodega."
            )

        line_ids_raw = request.form.getlist(
            "line_id[]"
        )

        actions = request.form.getlist(
            "action[]"
        )

        quantities = request.form.getlist(
            "quantity[]"
        )

        if not line_ids_raw:
            raise WorkOrderRequestServiceError(
                "No hay líneas para procesar."
            )

        if not (
            len(line_ids_raw)
            == len(actions)
            == len(quantities)
        ):
            raise WorkOrderRequestServiceError(
                "Los datos del pedido están incompletos."
            )

        request_lines_map = {
            int(line.id): line
            for line in request_obj.lines
        }

        processed_count = 0
        omitted_count = 0

        for index, line_id_raw in enumerate(
            line_ids_raw
        ):
            try:
                line_id = int(line_id_raw)
            except (TypeError, ValueError):
                raise WorkOrderRequestServiceError(
                    f"La línea {index + 1} no es válida."
                )

            line = request_lines_map.get(
                line_id
            )

            if not line:
                raise WorkOrderRequestServiceError(
                    "Una de las líneas no pertenece "
                    "a esta solicitud."
                )

            action = (
                actions[index]
                or ""
            ).strip().upper()

            quantity_raw = (
                quantities[index]
                or ""
            ).strip()

            if action == "OMITIR":
                omitted_count += 1
                continue

            if line.line_status not in {
                "SOLICITADA",
                "ATENDIDA_PARCIAL",
            }:
                raise WorkOrderRequestServiceError(
                    f"La línea del artículo "
                    f"{line.article.code if line.article else line.id} "
                    f"ya no está pendiente."
                )

            if (
                line.manager_review_status
                != "APROBADA"
            ):
                raise WorkOrderRequestServiceError(
                    f"La línea del artículo "
                    f"{line.article.code if line.article else line.id} "
                    f"no está aprobada."
                )

            if not quantity_raw:
                raise WorkOrderRequestServiceError(
                    f"Debe indicar la cantidad para "
                    f"{line.article.code if line.article else 'la línea'}."
                )

            try:
                quantity = Decimal(
                    quantity_raw
                )
            except (
                InvalidOperation,
                TypeError,
                ValueError,
            ):
                raise WorkOrderRequestServiceError(
                    f"La cantidad del artículo "
                    f"{line.article.code if line.article else line.id} "
                    f"no es válida."
                )

            article_code = (
                str(line.article.code).strip()
                if line.article
                and line.article.code
                else ""
            )

            try:
                article_code_number = int(
                    article_code
                )
            except (
                TypeError,
                ValueError,
            ):
                article_code_number = 0

            is_tool_line = (
                19000
                <= article_code_number
                <= 19999
            )

            if is_tool_line:
                if action != "PRESTAR":
                    raise WorkOrderRequestServiceError(
                        f"Debe seleccionar Prestar u Omitir "
                        f"para la herramienta {article_code}."
                    )

                mark_request_line_loaned(
                    request_line_id=line.id,
                    quantity=quantity,
                    performed_by_user_id=(
                        current_user.id
                    ),
                    commit=False,
                )

            else:
                if action != "ENTREGAR":
                    raise WorkOrderRequestServiceError(
                        f"Debe seleccionar Entregar u Omitir "
                        f"para el artículo {article_code}."
                    )

                attend_and_post_request_line(
                    request_line_id=line.id,
                    quantity=quantity,
                    performed_by_user_id=(
                        current_user.id
                    ),
                    commit=False,
                )

            processed_count += 1

        if processed_count == 0:
            raise WorkOrderRequestServiceError(
                "Debe seleccionar al menos una línea "
                "para entregar o prestar."
            )

        db.session.commit()

        message = (
            f"Pedido procesado correctamente. "
            f"Líneas procesadas: {processed_count}."
        )

        if omitted_count:
            message += (
                f" Líneas omitidas: "
                f"{omitted_count}."
            )

        flash(
            message,
            "success",
        )

    except (
        WorkOrderRequestServiceError,
        InvalidOperation,
        ValueError,
        TypeError,
    ) as exc:
        db.session.rollback()

        flash(
            str(exc),
            "danger",
        )

    except Exception as exc:
        db.session.rollback()

        print(
            "[PREPARE REQUEST BATCH ERROR] "
            f"request_id={request_id} "
            f"{type(exc).__name__}: {exc}"
        )

        flash(
            "No fue posible preparar el pedido.",
            "danger",
        )

    return redirect(
        request.referrer or "/"
    )

# =========================
# BODEGA → NO ENTREGADO
# =========================
@work_order_request_bp.route("/request-lines/<int:line_id>/not-delivered", methods=["POST"])
@login_required
def mark_request_line_not_delivered_action(line_id: int):
    try:
        mark_request_line_not_delivered(
            request_line_id=line_id,
            reason=request.form.get("reason") or "",
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Marcado como no entregado.", "success")

    except WorkOrderRequestServiceError as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# BODEGA → PRESTAR
# =========================
@work_order_request_bp.route("/request-lines/<int:line_id>/loan", methods=["POST"])
@login_required
def mark_request_line_loaned_action(line_id: int):
    try:
        qty = Decimal(request.form.get("quantity"))

        mark_request_line_loaned(
            request_line_id=line_id,
            quantity=qty,
            performed_by_user_id=current_user.id,
            commit=True,
        )

        flash("Línea prestada.", "success")

    except (WorkOrderRequestServiceError, InvalidOperation, ValueError) as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")


# =========================
# TERMINAL → CONFIRMAR ENTREGA
# =========================
@work_order_request_bp.route("/request-lines/<int:line_id>/confirm-to-work-order", methods=["POST"])
@login_required
def confirm_request_line_to_work_order_action(line_id: int):
    try:
        confirm_request_line_to_work_order(
            request_line_id=line_id,
            delivered_by_user_id=int(request.form.get("delivered_by_user_id")),
            received_by_user_id=int(request.form.get("received_by_user_id")),
            commit=True,
        )

        flash("Entrega confirmada.", "success")

    except (WorkOrderRequestServiceError, ValueError) as exc:
        flash(str(exc), "danger")

    return redirect(request.referrer or "/")
@work_order_request_bp.route("/tool-loans/<int:tool_loan_id>/confirm-return", methods=["POST"])
@login_required
def confirm_tool_return_action(tool_loan_id: int):
    try:
        loan = ToolLoan.query.get_or_404(tool_loan_id)

        if loan.loan_status != "DEVOLUCION_SOLICITADA":
            raise WorkOrderRequestServiceError(
                "Solo se pueden recibir herramientas con devolución solicitada."
            )

        add_stock(
            article_id=loan.article_id,
            warehouse_id=loan.warehouse_id,
            quantity=loan.quantity,
            performed_by_user_id=current_user.id,
            movement_type="DEVOLUCION_HERRAMIENTA",
            reason=f"Recepción devolución herramienta OT {loan.work_order.number if loan.work_order else ''}",
            reference_type="TOOL_LOAN",
            reference_id=loan.id,
            reference_number=loan.work_order.number if loan.work_order else None,
            commit=False,
        )

        loan.loan_status = "DEVUELTA"
        loan.received_return_by_user_id = current_user.id

        db.session.commit()

        flash("Herramienta recibida correctamente.", "success")

    except (WorkOrderRequestServiceError, InventoryServiceError) as exc:
        db.session.rollback()
        flash(str(exc), "danger")

    except Exception as exc:
        db.session.rollback()
        flash(f"Error al recibir herramienta: {exc}", "danger")

    return redirect(request.referrer or "/")