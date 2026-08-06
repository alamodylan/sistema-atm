from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.models.article import Article
from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLine
from app.models.work_order_request import WorkOrderRequest
from app.models.work_order_request_line import WorkOrderRequestLine
from app.services.audit_service import log_action
from app.models.tool_loan import ToolLoan
from app.models.unit import Unit
from app.services.request_routing_service import resolve_request_routing
from app.services.inventory_service import (
    InventoryServiceError,
    get_warehouse_stock_record,
    subtract_stock,
)


class WorkOrderRequestServiceError(Exception):
    pass


TERMINAL_LINE_STATUSES = {"ENTREGADA", "NO_ENTREGADA", "CANCELADA", "PRESTADA"}


def _to_decimal(value) -> Decimal:
    qty = Decimal(str(value))
    if qty <= 0:
        raise WorkOrderRequestServiceError("La cantidad debe ser mayor a 0.")
    return qty


def _sync_request_status(request_obj: WorkOrderRequest) -> None:
    lines = list(request_obj.lines)
    if not lines:
        return

    active_lines = [line for line in lines if line.line_status != "CANCELADA"]

    if not active_lines:
        request_obj.request_status = "CANCELADA"
        return

    if all(line.line_status in TERMINAL_LINE_STATUSES for line in active_lines):
        request_obj.request_status = "ATENDIDA"
        return

    if request_obj.request_status == "CANCELADA":
        request_obj.request_status = "ENVIADA"

def _is_tool_article_code(code: str) -> bool:
    try:
        number = int(str(code).strip())
        return 19000 <= number <= 19999
    except Exception:
        return False

def create_request(
    *,
    work_order_id: int,
    requested_by_user_id: int,
    mechanic_id: int | None = None,
    commit: bool = True,
) -> WorkOrderRequest:
    work_order = WorkOrder.query.get(work_order_id)
    if not work_order:
        raise WorkOrderRequestServiceError("La OT no existe.")

    if work_order.status != "EN_PROCESO":
        raise WorkOrderRequestServiceError("Solo se pueden crear solicitudes para OTs en proceso.")

    existing_open = (
        WorkOrderRequest.query
        .filter_by(
            work_order_id=work_order_id,
            requested_by_user_id=requested_by_user_id,
            request_status="ABIERTA",
        )
        .order_by(WorkOrderRequest.created_at.desc())
        .first()
    )
    if existing_open:
        return existing_open

    request_obj = WorkOrderRequest(
        work_order_id=work_order_id,
        requested_by_user_id=requested_by_user_id,
        mechanic_id=mechanic_id,
        request_status="ABIERTA",
    )

    db.session.add(request_obj)
    db.session.flush()

    log_action(
        user_id=requested_by_user_id,
        action="CREATE_WORK_ORDER_REQUEST",
        table_name="work_order_requests",
        record_id=str(request_obj.id),
        details={
            "work_order_id": work_order_id,
            "mechanic_id": mechanic_id,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return request_obj


def add_request_line(
    *,
    request_id: int,
    article_id: int,
    quantity_requested,
    notes: str | None = None,
    commit: bool = True,
) -> WorkOrderRequestLine:
    if not request_id:
        raise WorkOrderRequestServiceError("La solicitud no existe.")

    request_obj = WorkOrderRequest.query.get(request_id)
    if not request_obj:
        raise WorkOrderRequestServiceError("La solicitud no existe.")

    if request_obj.request_status != "ABIERTA":
        raise WorkOrderRequestServiceError("Solo se pueden agregar líneas a solicitudes abiertas.")

    article = Article.query.get(article_id)
    if not article:
        raise WorkOrderRequestServiceError("El artículo no existe.")

    qty = _to_decimal(quantity_requested)

    line = WorkOrderRequestLine(
        work_order_request_id=request_id,
        article_id=article_id,
        quantity_requested=qty,
        quantity_attended=Decimal("0"),
        notes=(notes or "").strip() or None,
        line_status="SOLICITADA",
        manager_review_status="PENDIENTE",
    )

    db.session.add(line)
    db.session.flush()

    log_action(
        user_id=request_obj.requested_by_user_id,
        action="ADD_WORK_ORDER_REQUEST_LINE",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "request_id": request_id,
            "article_id": article_id,
            "quantity_requested": str(qty),
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return line


def cancel_request_line(
    *,
    request_line_id: int,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequestLine:
    line = WorkOrderRequestLine.query.get(request_line_id)
    if not line:
        raise WorkOrderRequestServiceError("La línea no existe.")

    request_obj = line.work_order_request
    if request_obj.request_status != "ABIERTA":
        raise WorkOrderRequestServiceError("Solo se pueden cancelar líneas de solicitudes abiertas.")

    line.line_status = "CANCELADA"
    _sync_request_status(request_obj)
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="CANCEL_WORK_ORDER_REQUEST_LINE",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={"line_status": line.line_status},
        commit=False,
    )

    if commit:
        db.session.commit()

    return line


def void_request_line(
    *,
    request_line_id: int,
    reason: str,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequestLine:
    """
    Anula una línea de solicitud de material mientras todavía no haya sido
    recibida por el mecánico ni haya generado afectación de inventario.

    La línea no se elimina físicamente. Se conserva como CANCELADA junto con:
    - motivo de anulación;
    - usuario que anuló;
    - fecha y hora de anulación.
    """

    line = WorkOrderRequestLine.query.get(request_line_id)

    if not line:
        raise WorkOrderRequestServiceError(
            "La línea de solicitud no existe."
        )

    reason = (reason or "").strip()

    if not reason:
        raise WorkOrderRequestServiceError(
            "Debe indicar el motivo de la anulación."
        )

    if len(reason) < 5:
        raise WorkOrderRequestServiceError(
            "El motivo de la anulación debe contener al menos 5 caracteres."
        )

    if line.line_status == "CANCELADA":
        raise WorkOrderRequestServiceError(
            "La línea ya se encuentra anulada."
        )

    if line.line_status == "PRESTADA":
        raise WorkOrderRequestServiceError(
            "La línea corresponde a una herramienta prestada y no puede anularse."
        )

    request_obj = line.work_order_request

    if not request_obj:
        raise WorkOrderRequestServiceError(
            "La línea no tiene una solicitud asociada."
        )

    work_order = request_obj.work_order

    if not work_order:
        raise WorkOrderRequestServiceError(
            "La solicitud no tiene una orden de trabajo asociada."
        )

    # Una WorkOrderLine significa que el mecánico ya escaneó y recibió
    # el material. En ese momento ya se aplicó el rebajo de inventario.
    existing_work_order_line = (
        WorkOrderLine.query
        .filter(
            WorkOrderLine.request_line_id == line.id
        )
        .first()
    )

    if existing_work_order_line:
        raise WorkOrderRequestServiceError(
            "No se puede anular la línea porque el material ya fue "
            "recibido por el mecánico y afectó el inventario."
        )

    # Las herramientas afectan inventario al registrarse el préstamo,
    # antes del flujo normal de recepción de artículos.
    existing_tool_loan = (
        ToolLoan.query
        .filter(
            ToolLoan.request_line_id == line.id
        )
        .first()
    )

    if existing_tool_loan:
        raise WorkOrderRequestServiceError(
            "No se puede anular la línea porque ya generó un préstamo "
            "de herramienta y afectó el inventario."
        )

    previous_status = line.line_status
    previous_quantity_attended = Decimal(
        str(line.quantity_attended or 0)
    )

    line.line_status = "CANCELADA"
    line.cancel_reason = reason
    line.cancelled_by_user_id = performed_by_user_id
    line.cancelled_at = db.func.now()

    _sync_request_status(request_obj)

    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="VOID_WORK_ORDER_REQUEST_LINE",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "work_order_id": work_order.id,
            "work_order_number": work_order.number,
            "request_id": request_obj.id,
            "request_line_id": line.id,
            "article_id": line.article_id,
            "article_code": (
                line.article.code
                if line.article
                else None
            ),
            "previous_status": previous_status,
            "new_status": line.line_status,
            "quantity_requested": str(
                line.quantity_requested or 0
            ),
            "quantity_attended": str(
                previous_quantity_attended
            ),
            "cancel_reason": reason,
            "cancelled_by_user_id": performed_by_user_id,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return line

def reject_request_line_by_management(
    *,
    request_line_id: int,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequestLine:
    line = WorkOrderRequestLine.query.get(request_line_id)
    if not line:
        raise WorkOrderRequestServiceError("La línea no existe.")

    request_obj = line.work_order_request
    if request_obj.request_status != "ENVIADA":
        raise WorkOrderRequestServiceError("Solo se pueden rechazar líneas de solicitudes enviadas.")

    if request_obj.sent_to_warehouse_at:
        raise WorkOrderRequestServiceError("La solicitud ya fue enviada a bodega y no puede rechazarse desde jefatura.")

    line.manager_review_status = "RECHAZADA"
    line.manager_reviewed_by_user_id = performed_by_user_id
    line.manager_reviewed_at = db.func.now()
    line.line_status = "CANCELADA"

    _sync_request_status(request_obj)
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="REJECT_REQUEST_LINE_BY_MANAGEMENT",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "request_id": request_obj.id,
            "line_status": line.line_status,
            "manager_review_status": line.manager_review_status,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return line


def update_request_line_requested_quantity(
    *,
    request_line_id: int,
    quantity_requested,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequestLine:
    line = WorkOrderRequestLine.query.get(request_line_id)
    if not line:
        raise WorkOrderRequestServiceError("La línea no existe.")

    request_obj = line.work_order_request
    if request_obj.request_status != "ENVIADA":
        raise WorkOrderRequestServiceError("Solo se puede modificar cantidad en solicitudes enviadas.")

    if request_obj.sent_to_warehouse_at:
        raise WorkOrderRequestServiceError("La solicitud ya fue enviada a bodega y no puede modificarse desde jefatura.")

    if line.line_status == "CANCELADA":
        raise WorkOrderRequestServiceError("No se puede modificar una línea cancelada.")

    qty = _to_decimal(quantity_requested)

    line.manager_review_status = "APROBADA"
    line.manager_reviewed_by_user_id = performed_by_user_id
    line.manager_reviewed_at = db.func.now()

    line.quantity_requested = qty

    if line.quantity_attended > qty:
        line.quantity_attended = qty

    if line.quantity_attended == 0:
        line.line_status = "SOLICITADA"
    elif line.quantity_attended < line.quantity_requested:
        line.line_status = "ATENDIDA_PARCIAL"
    else:
        line.line_status = "ENTREGADA"

    _sync_request_status(request_obj)
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="UPDATE_REQUEST_LINE_REQUESTED_QUANTITY",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "request_id": request_obj.id,
            "new_quantity_requested": str(qty),
            "line_status": line.line_status,
            "manager_review_status": line.manager_review_status,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return line


def undo_manager_decision(
    *,
    request_line_id: int,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequestLine:
    line = WorkOrderRequestLine.query.get(request_line_id)
    if not line:
        raise WorkOrderRequestServiceError("La línea no existe.")

    request_obj = line.work_order_request
    if request_obj.request_status != "ENVIADA":
        raise WorkOrderRequestServiceError("Solo se puede deshacer en solicitudes enviadas a jefatura.")

    if request_obj.sent_to_warehouse_at:
        raise WorkOrderRequestServiceError("La solicitud ya fue enviada a bodega y no puede revertirse.")

    line.manager_review_status = "PENDIENTE"
    line.manager_reviewed_by_user_id = None
    line.manager_reviewed_at = None
    line.line_status = "SOLICITADA"
    line.not_delivered_reason = None

    _sync_request_status(request_obj)
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="UNDO_MANAGER_DECISION",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "request_id": request_obj.id,
            "manager_review_status": line.manager_review_status,
            "line_status": line.line_status,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return line


def send_request(
    *,
    request_id: int,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequest:

    if not request_id:
        raise WorkOrderRequestServiceError("La solicitud no existe.")

    request_obj = WorkOrderRequest.query.get(request_id)

    if not request_obj:
        raise WorkOrderRequestServiceError("La solicitud no existe.")

    if request_obj.request_status != "ABIERTA":
        raise WorkOrderRequestServiceError(
            "Solo solicitudes abiertas pueden enviarse."
        )

    active_lines_count = sum(
        1 for line in request_obj.lines
        if line.line_status != "CANCELADA"
    )

    if active_lines_count == 0:
        raise WorkOrderRequestServiceError(
            "No se puede enviar una solicitud sin líneas activas."
        )

    work_order = request_obj.work_order

    if not work_order:
        raise WorkOrderRequestServiceError(
            "La solicitud no tiene OT asociada."
        )

    # =====================================================
    # ROUTING CONFIGURABLE
    # =====================================================

    review_site_id = work_order.site_id

    routing = resolve_request_routing(
        origin_site_id=work_order.site_id,
        request_type="WORK_ORDER_REQUEST",
    )

    request_obj.request_status = "ENVIADA"

    if routing.get("has_rule"):

        routing_mode = routing.get("routing_mode")

        # =================================================
        # DASHBOARD JEFATURA LOCAL
        # =================================================

        if routing_mode == "LOCAL_MANAGER_DASHBOARD":

            review_site_id = work_order.site_id

        # =================================================
        # DASHBOARD JEFATURA OTRO PREDIO
        # =================================================

        elif routing_mode == "OTHER_SITE_MANAGER_DASHBOARD":

            review_site_id = (
                routing.get("target_site_id")
                or work_order.site_id
            )

        # =================================================
        # DIRECTO A BODEGA
        # =================================================

        elif routing_mode == "DIRECT_TO_WAREHOUSE":

            review_site_id = None

            request_obj.approved_by_user_id = performed_by_user_id
            request_obj.approved_at = db.func.now()

            request_obj.sent_to_warehouse_by_user_id = (
                performed_by_user_id
            )

            request_obj.sent_to_warehouse_at = db.func.now()

            for line in request_obj.lines:

                if line.line_status == "CANCELADA":
                    continue

                line.manager_review_status = "APROBADA"
                line.manager_reviewed_by_user_id = performed_by_user_id
                line.manager_reviewed_at = db.func.now()

    request_obj.review_site_id = review_site_id

    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="SEND_WORK_ORDER_REQUEST",
        table_name="work_order_requests",
        record_id=str(request_obj.id),
        details={
            "status": request_obj.request_status,
            "review_site_id": review_site_id,
            "routing_mode": routing.get("routing_mode"),
            "routing_has_rule": routing.get("has_rule", False),
            "sent_direct_to_warehouse": bool(
                request_obj.sent_to_warehouse_at
            ),
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return request_obj


def send_request_to_warehouse(
    *,
    request_id: int,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequest:
    request_obj = WorkOrderRequest.query.get(request_id)
    if not request_obj:
        raise WorkOrderRequestServiceError("La solicitud no existe.")

    if request_obj.request_status != "ENVIADA":
        raise WorkOrderRequestServiceError("Solo solicitudes enviadas por mecánico pueden pasar a bodega.")

    if request_obj.sent_to_warehouse_at:
        raise WorkOrderRequestServiceError("La solicitud ya fue enviada a bodega.")

    lines = list(request_obj.lines)

    if not lines:
        raise WorkOrderRequestServiceError("No hay líneas en la solicitud.")

    has_approved = False

    for line in lines:
        if line.manager_review_status == "PENDIENTE":
            raise WorkOrderRequestServiceError("Debe decidir todas las líneas antes de enviar a bodega.")

        if line.manager_review_status == "APROBADA":
            has_approved = True

    if not has_approved:
        raise WorkOrderRequestServiceError("Debe haber al menos una línea aprobada.")

    request_obj.approved_by_user_id = performed_by_user_id
    request_obj.approved_at = db.func.now()
    request_obj.sent_to_warehouse_by_user_id = performed_by_user_id
    request_obj.sent_to_warehouse_at = db.func.now()

    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="SEND_REQUEST_TO_WAREHOUSE",
        table_name="work_order_requests",
        record_id=str(request_obj.id),
        details={
            "approved_by_user_id": performed_by_user_id,
            "sent_to_warehouse_by_user_id": performed_by_user_id,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return request_obj

def review_request_and_send_to_warehouse(
    *,
    request_id: int,
    decisions: list[dict],
    performed_by_user_id: int,
    active_site_id: int,
    commit: bool = True,
) -> dict:
    """
    Revisa todas las líneas de una solicitud de OT y finaliza
    la revisión de jefatura en una sola transacción.

    Cada elemento de decisions debe contener:

        {
            "line_id": 123,
            "decision": "APROBADA" | "RECHAZADA",
            "quantity": "5",
            "reason": "Motivo opcional"
        }

    Comportamiento:
    - APROBADA:
        actualiza la cantidad solicitada con la cantidad aprobada.
    - RECHAZADA:
        marca la línea como rechazada y cancelada.
    - Si hay al menos una aprobada:
        envía la solicitud a bodega.
    - Si todas son rechazadas:
        cancela la solicitud y no la envía a bodega.
    - Todo se confirma con un único commit.
    """

    if not request_id:
        raise WorkOrderRequestServiceError(
            "La solicitud no existe."
        )

    if not active_site_id:
        raise WorkOrderRequestServiceError(
            "No hay un predio activo seleccionado."
        )

    if not isinstance(decisions, list) or not decisions:
        raise WorkOrderRequestServiceError(
            "Debe indicar la decisión de las líneas."
        )

    try:
        request_id = int(request_id)
        active_site_id = int(active_site_id)
        performed_by_user_id = int(
            performed_by_user_id
        )

    except (TypeError, ValueError) as exc:
        raise WorkOrderRequestServiceError(
            "Los datos de la solicitud no son válidos."
        ) from exc

    # =====================================================
    # BLOQUEAR SOLICITUD
    # =====================================================
    #
    # Evita que dos personas revisen o envíen la misma
    # solicitud al mismo tiempo.
    # =====================================================

    request_obj = (
        db.session.query(
            WorkOrderRequest
        )
        .join(
            WorkOrder,
            WorkOrder.id
            == WorkOrderRequest.work_order_id,
        )
        .filter(
            WorkOrderRequest.id == request_id,
            db.or_(
                WorkOrderRequest.review_site_id
                == active_site_id,
                db.and_(
                    WorkOrderRequest.review_site_id.is_(
                        None
                    ),
                    WorkOrder.site_id
                    == active_site_id,
                ),
            ),
        )
        .with_for_update()
        .first()
    )

    if not request_obj:
        raise WorkOrderRequestServiceError(
            "La solicitud no existe o no corresponde "
            "al predio activo."
        )

    if request_obj.request_status != "ENVIADA":
        raise WorkOrderRequestServiceError(
            "Solo se pueden revisar solicitudes enviadas."
        )

    if request_obj.sent_to_warehouse_at:
        raise WorkOrderRequestServiceError(
            "La solicitud ya fue enviada a bodega."
        )

    # =====================================================
    # CARGAR Y BLOQUEAR TODAS LAS LÍNEAS
    # =====================================================

    # =====================================================
    # CARGAR Y BLOQUEAR ÚNICAMENTE LAS LÍNEAS
    # =====================================================
    #
    # No se usa joinedload aquí porque genera LEFT OUTER JOIN
    # y PostgreSQL no permite FOR UPDATE sobre el lado nullable
    # de un outer join.
    # =====================================================

    request_lines = (
        WorkOrderRequestLine.query
        .filter(
            WorkOrderRequestLine.work_order_request_id
            == request_obj.id,
        )
        .order_by(
            WorkOrderRequestLine.id.asc(),
        )
        .with_for_update()
        .all()
    )

    if not request_lines:
        raise WorkOrderRequestServiceError(
            "La solicitud no tiene líneas."
        )

    # =====================================================
    # CARGAR LAS UNIDADES EN UNA CONSULTA SEPARADA
    # =====================================================
    #
    # Solo necesitamos el código de unidad para validar UND.
    # Se carga en bloque, sin N+1 y sin afectar el bloqueo.
    # =====================================================

    article_ids = {
        int(line.article_id)
        for line in request_lines
        if line.article_id
    }

    article_unit_codes = {}

    if article_ids:
        article_unit_rows = (
            db.session.query(
                Article.id.label("article_id"),
                Unit.code.label("unit_code"),
            )
            .outerjoin(
                Unit,
                Unit.id == Article.unit_id,
            )
            .filter(
                Article.id.in_(article_ids)
            )
            .all()
        )

        article_unit_codes = {
            int(row.article_id): (
                row.unit_code or ""
            ).strip().upper()
            for row in article_unit_rows
        }

    if not request_lines:
        raise WorkOrderRequestServiceError(
            "La solicitud no tiene líneas."
        )

    lines_by_id = {
        int(line.id): line
        for line in request_lines
    }

    normalized_decisions = {}
    duplicated_line_ids = set()

    # =====================================================
    # NORMALIZAR PAYLOAD
    # =====================================================

    for position, raw_decision in enumerate(
        decisions,
        start=1,
    ):
        if not isinstance(raw_decision, dict):
            raise WorkOrderRequestServiceError(
                f"La decisión #{position} no es válida."
            )

        raw_line_id = raw_decision.get(
            "line_id"
        )

        try:
            line_id = int(raw_line_id)

        except (TypeError, ValueError) as exc:
            raise WorkOrderRequestServiceError(
                f"La línea indicada en la posición "
                f"{position} no es válida."
            ) from exc

        if line_id in normalized_decisions:
            duplicated_line_ids.add(line_id)

        normalized_decisions[line_id] = (
            raw_decision
        )

    if duplicated_line_ids:
        duplicated_text = ", ".join(
            str(line_id)
            for line_id in sorted(
                duplicated_line_ids
            )
        )

        raise WorkOrderRequestServiceError(
            "Se recibieron decisiones duplicadas para "
            f"las líneas: {duplicated_text}."
        )

    unknown_line_ids = (
        set(normalized_decisions.keys())
        - set(lines_by_id.keys())
    )

    if unknown_line_ids:
        unknown_text = ", ".join(
            str(line_id)
            for line_id in sorted(
                unknown_line_ids
            )
        )

        raise WorkOrderRequestServiceError(
            "Las siguientes líneas no pertenecen a "
            f"la solicitud: {unknown_text}."
        )

    now = datetime.now(UTC)

    approved_count = 0
    rejected_count = 0
    audit_lines = []

    # =====================================================
    # APLICAR DECISIONES
    # =====================================================

    for line_id, raw_decision in (
        normalized_decisions.items()
    ):
        line = lines_by_id[line_id]

        decision = (
            raw_decision.get("decision")
            or ""
        ).strip().upper()

        if decision not in {
            "APROBADA",
            "RECHAZADA",
        }:
            raise WorkOrderRequestServiceError(
                f"Debe aprobar o rechazar la línea "
                f"{line.id}."
            )

        previous_quantity = Decimal(
            str(line.quantity_requested or 0)
        )

        previous_review_status = (
            line.manager_review_status
            or "PENDIENTE"
        )

        previous_line_status = (
            line.line_status
            or "SOLICITADA"
        )

        if decision == "APROBADA":
            raw_quantity = raw_decision.get(
                "quantity"
            )

            if raw_quantity in {
                None,
                "",
            }:
                raw_quantity = (
                    line.quantity_requested
                )

            try:
                approved_quantity = _to_decimal(
                    raw_quantity
                )

            except (
                ValueError,
                ArithmeticError,
            ) as exc:
                raise WorkOrderRequestServiceError(
                    f"La cantidad aprobada de la línea "
                    f"{line.id} no es válida."
                ) from exc

            unit_code = article_unit_codes.get(
                int(line.article_id),
                "",
            )

            if (
                unit_code == "UND"
                and approved_quantity
                != approved_quantity.to_integral_value()
            ):
                raise WorkOrderRequestServiceError(
                    f"El artículo de la línea {line.id} "
                    "usa unidad UND y solo admite "
                    "cantidades enteras."
                )

            line.manager_review_status = (
                "APROBADA"
            )

            line.manager_reviewed_by_user_id = (
                performed_by_user_id
            )

            line.manager_reviewed_at = now
            line.quantity_requested = (
                approved_quantity
            )

            line.not_delivered_reason = None
            line.cancel_reason = None
            line.cancelled_by_user_id = None
            line.cancelled_at = None

            attended_quantity = Decimal(
                str(line.quantity_attended or 0)
            )

            if (
                attended_quantity
                > approved_quantity
            ):
                line.quantity_attended = (
                    approved_quantity
                )

                attended_quantity = (
                    approved_quantity
                )

            if attended_quantity <= 0:
                line.line_status = "SOLICITADA"

            elif (
                attended_quantity
                < approved_quantity
            ):
                line.line_status = (
                    "ATENDIDA_PARCIAL"
                )

            else:
                line.line_status = "ENTREGADA"

            approved_count += 1

            audit_lines.append({
                "line_id": line.id,
                "article_id": line.article_id,
                "decision": "APROBADA",
                "previous_quantity": str(
                    previous_quantity
                ),
                "approved_quantity": str(
                    approved_quantity
                ),
                "previous_review_status": (
                    previous_review_status
                ),
                "previous_line_status": (
                    previous_line_status
                ),
                "new_line_status": (
                    line.line_status
                ),
            })

        else:
            reason = (
                raw_decision.get("reason")
                or ""
            ).strip()

            line.manager_review_status = (
                "RECHAZADA"
            )

            line.manager_reviewed_by_user_id = (
                performed_by_user_id
            )

            line.manager_reviewed_at = now
            line.line_status = "CANCELADA"

            # Se guarda el motivo si el usuario lo indicó.
            # No se obliga porque el flujo anterior tampoco
            # lo requería para rechazar.
            line.not_delivered_reason = (
                reason or None
            )

            rejected_count += 1

            audit_lines.append({
                "line_id": line.id,
                "article_id": line.article_id,
                "decision": "RECHAZADA",
                "reason": reason or None,
                "previous_quantity": str(
                    previous_quantity
                ),
                "previous_review_status": (
                    previous_review_status
                ),
                "previous_line_status": (
                    previous_line_status
                ),
                "new_line_status": (
                    line.line_status
                ),
            })

    # =====================================================
    # VALIDAR QUE TODAS LAS LÍNEAS TENGAN DECISIÓN
    # =====================================================

    pending_line_ids = [
        int(line.id)
        for line in request_lines
        if (
            line.manager_review_status
            or "PENDIENTE"
        ) == "PENDIENTE"
    ]

    if pending_line_ids:
        pending_text = ", ".join(
            str(line_id)
            for line_id in pending_line_ids
        )

        raise WorkOrderRequestServiceError(
            "Debe aprobar o rechazar todas las líneas. "
            f"Pendientes: {pending_text}."
        )

    # =====================================================
    # FINALIZAR SOLICITUD
    # =====================================================

    sent_to_warehouse = approved_count > 0

    request_obj.approved_by_user_id = (
        performed_by_user_id
    )

    request_obj.approved_at = now

    if sent_to_warehouse:
        request_obj.request_status = "ENVIADA"

        request_obj.sent_to_warehouse_by_user_id = (
            performed_by_user_id
        )

        request_obj.sent_to_warehouse_at = now

    else:
        # Todas las líneas fueron rechazadas.
        # La solicitud se cierra sin enviarla a bodega.
        request_obj.request_status = "CANCELADA"

        request_obj.sent_to_warehouse_by_user_id = (
            None
        )

        request_obj.sent_to_warehouse_at = None

    db.session.flush()

    # Un único registro de auditoría para toda la operación.
    # Esto es más liviano que generar un log y un flush
    # independiente por cada línea.
    log_action(
        user_id=performed_by_user_id,
        action=(
            "REVIEW_AND_SEND_WORK_ORDER_REQUEST"
        ),
        table_name="work_order_requests",
        record_id=str(request_obj.id),
        details={
            "request_id": request_obj.id,
            "work_order_id": (
                request_obj.work_order_id
            ),
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "sent_to_warehouse": (
                sent_to_warehouse
            ),
            "request_status": (
                request_obj.request_status
            ),
            "lines": audit_lines,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return {
        "request": request_obj,
        "request_id": int(request_obj.id),
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "sent_to_warehouse": sent_to_warehouse,
        "request_status": (
            request_obj.request_status
        ),
    }


def attend_request_line(
    *,
    request_line_id: int,
    quantity,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequestLine:
    line = WorkOrderRequestLine.query.get(request_line_id)
    if not line:
        raise WorkOrderRequestServiceError("La línea no existe.")

    request_obj = line.work_order_request
    if request_obj.request_status != "ENVIADA":
        raise WorkOrderRequestServiceError("Solo se pueden atender líneas de solicitudes enviadas.")

    if not request_obj.sent_to_warehouse_at:
        raise WorkOrderRequestServiceError("La solicitud aún no ha sido enviada a bodega.")

    if line.line_status == "CANCELADA":
        raise WorkOrderRequestServiceError("No se puede atender una línea cancelada.")

    if line.manager_review_status != "APROBADA":
        raise WorkOrderRequestServiceError("La línea no fue aprobada por jefatura.")

    qty = _to_decimal(quantity)

    remaining = line.quantity_requested - line.quantity_attended

    work_order = request_obj.work_order
    stock_record = get_warehouse_stock_record(line.article_id, work_order.warehouse_id)

    if not stock_record:
        raise WorkOrderRequestServiceError("No hay stock registrado para este artículo en la bodega de la OT.")

    available = Decimal(str(stock_record.available_quantity or 0))

    # ==============================
    # 🔥 NUEVA REGLA DE NEGOCIO
    # ==============================

    if available >= remaining:
        # ✔ Hay stock suficiente → debe entregar EXACTO
        if qty != remaining:
            raise WorkOrderRequestServiceError(
                f"Debe entregar exactamente {remaining} unidades (cantidad aprobada por jefatura)."
            )
    else:
        # ✔ No hay stock suficiente → puede entregar lo disponible
        if qty > available:
            raise WorkOrderRequestServiceError(
                f"No puede entregar más de lo disponible en stock ({available})."
            )

    if qty > remaining:
        raise WorkOrderRequestServiceError("No puede atender más de lo solicitado.")

    # ==============================

    line.quantity_attended += qty

    if line.quantity_attended == line.quantity_requested:
        line.line_status = "ENTREGADA"
    else:
        line.line_status = "ATENDIDA_PARCIAL"

    _sync_request_status(request_obj)
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="ATTEND_REQUEST_LINE",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "attended": str(qty),
            "total_attended": str(line.quantity_attended),
            "line_status": line.line_status,
            "warehouse_id": work_order.warehouse_id,
            "available_quantity": str(available),
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return line


def attend_and_post_request_line(
    *,
    request_line_id: int,
    quantity,
    performed_by_user_id: int,
    commit: bool = True,
) -> tuple[WorkOrderRequestLine, WorkOrderLine]:
    """
    Atiende una línea desde Bodega y aplica inmediatamente:

    - cantidad atendida;
    - estado de la línea;
    - rebajo de inventario;
    - movimiento SALIDA_OT en kardex;
    - creación o actualización de WorkOrderLine;
    - recepción automática.

    El proceso se ejecuta dentro de la misma transacción.

    Esta función sustituye el flujo anterior:

        Preparar en Bodega
        -> esperar recepción en Terminal Taller
        -> rebajar inventario

    Nuevo flujo:

        Preparar en Bodega
        -> rebajar inventario
        -> registrar recepción automática
    """

    # Bloquea la línea para evitar que dos clics o peticiones
    # simultáneas atiendan la misma cantidad dos veces.
    locked_line = (
        WorkOrderRequestLine.query
        .filter(
            WorkOrderRequestLine.id == request_line_id,
        )
        .with_for_update()
        .first()
    )

    if not locked_line:
        raise WorkOrderRequestServiceError(
            "La línea no existe."
        )

    line = attend_request_line(
        request_line_id=locked_line.id,
        quantity=quantity,
        performed_by_user_id=performed_by_user_id,
        commit=False,
    )

    work_order_line = confirm_request_line_to_work_order(
        request_line_id=line.id,
        delivered_by_user_id=performed_by_user_id,
        received_by_user_id=performed_by_user_id,
        auto_received=True,
        commit=False,
    )

    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="ATTEND_AND_POST_REQUEST_LINE",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "request_line_id": line.id,
            "request_id": line.work_order_request_id,
            "article_id": line.article_id,
            "quantity_processed": str(quantity),
            "quantity_attended": str(
                line.quantity_attended or 0
            ),
            "line_status": line.line_status,
            "work_order_line_id": work_order_line.id,
            "inventory_posted": True,
            "auto_received": True,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return line, work_order_line

def mark_request_line_not_delivered(
    *,
    request_line_id: int,
    reason: str,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequestLine:
    line = WorkOrderRequestLine.query.get(request_line_id)
    if not line:
        raise WorkOrderRequestServiceError("La línea no existe.")

    request_obj = line.work_order_request
    if request_obj.request_status != "ENVIADA":
        raise WorkOrderRequestServiceError("Solo se pueden marcar líneas no entregadas en solicitudes enviadas.")

    if not request_obj.sent_to_warehouse_at:
        raise WorkOrderRequestServiceError("La solicitud aún no ha sido enviada a bodega.")

    if line.manager_review_status != "APROBADA":
        raise WorkOrderRequestServiceError("La línea no fue aprobada por jefatura.")

    line.line_status = "NO_ENTREGADA"
    line.not_delivered_reason = (reason or "").strip() or None

    _sync_request_status(request_obj)
    db.session.flush()

    log_action(
        user_id=performed_by_user_id,
        action="MARK_REQUEST_LINE_NOT_DELIVERED",
        table_name="work_order_request_lines",
        record_id=str(line.id),
        details={
            "line_status": line.line_status,
            "reason": line.not_delivered_reason,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return line


def mark_request_line_loaned(
    *,
    request_line_id: int,
    quantity,
    performed_by_user_id: int,
    commit: bool = True,
) -> WorkOrderRequestLine:
    line = WorkOrderRequestLine.query.get(request_line_id)
    if not line:
        raise WorkOrderRequestServiceError("La línea no existe.")

    request_obj = line.work_order_request

    if request_obj.request_status != "ENVIADA":
        raise WorkOrderRequestServiceError("Solo se pueden prestar líneas de solicitudes enviadas.")

    if not request_obj.sent_to_warehouse_at:
        raise WorkOrderRequestServiceError("La solicitud aún no ha sido enviada a bodega.")

    if line.manager_review_status != "APROBADA":
        raise WorkOrderRequestServiceError("La línea no fue aprobada por jefatura.")

    if not line.article:
        raise WorkOrderRequestServiceError("La línea no tiene artículo asociado.")

    if not _is_tool_article_code(line.article.code):
        raise WorkOrderRequestServiceError(
            "Solo los artículos con código entre 19000 y 19999 pueden prestarse como herramienta."
        )

    qty = _to_decimal(quantity)
    remaining = line.quantity_requested - line.quantity_attended

    if qty > remaining:
        raise WorkOrderRequestServiceError("No puede prestar más de lo solicitado.")

    work_order = request_obj.work_order

    stock_record = get_warehouse_stock_record(
        line.article_id,
        work_order.warehouse_id,
    )

    if not stock_record:
        raise WorkOrderRequestServiceError(
            "No hay stock registrado para esta herramienta en la bodega de la OT."
        )

    available = Decimal(str(stock_record.available_quantity or 0))

    if qty > available:
        raise WorkOrderRequestServiceError(
            f"No hay suficiente stock disponible para prestar esta herramienta. Disponible: {available}."
        )

    try:
        subtract_stock(
            article_id=line.article_id,
            warehouse_id=work_order.warehouse_id,
            quantity=qty,
            performed_by_user_id=performed_by_user_id,
            movement_type="PRESTAMO_HERRAMIENTA",
            reason=f"Préstamo de herramienta OT {work_order.number}",
            reference_type="TOOL_LOAN",
            reference_id=line.id,
            reference_number=work_order.number,
            commit=False,
        )

    except InventoryServiceError as exc:
        raise WorkOrderRequestServiceError(str(exc)) from exc

    line.quantity_attended += qty

    if line.quantity_attended == line.quantity_requested:
        line.line_status = "PRESTADA"
    else:
        line.line_status = "ATENDIDA_PARCIAL"

    tool_loan = ToolLoan(
        work_order_id=work_order.id,
        request_line_id=line.id,
        article_id=line.article_id,
        warehouse_id=work_order.warehouse_id,
        requested_by_user_id=request_obj.requested_by_user_id,
        delivered_by_user_id=performed_by_user_id,
        quantity=qty,
        loan_status="PRESTADA",
        notes=line.notes,
    )

    db.session.add(tool_loan)
    db.session.flush()

    _sync_request_status(request_obj)

    log_action(
        user_id=performed_by_user_id,
        action="MARK_REQUEST_LINE_LOANED",
        table_name="tool_loans",
        record_id=str(tool_loan.id),
        details={
            "work_order_id": work_order.id,
            "work_order_number": work_order.number,
            "request_id": request_obj.id,
            "request_line_id": line.id,
            "article_id": line.article_id,
            "article_code": line.article.code,
            "quantity_loaned": str(qty),
            "total_attended": str(line.quantity_attended),
            "line_status": line.line_status,
            "loan_status": tool_loan.loan_status,
            "warehouse_id": work_order.warehouse_id,
            "available_quantity_before": str(available),
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return line


def confirm_request_line_to_work_order(
    *,
    request_line_id: int,
    delivered_by_user_id: int,
    received_by_user_id: int | None = None,
    auto_received: bool = False,
    commit: bool = True,
) -> WorkOrderLine:
    """
    Registra inmediatamente en la OT la cantidad atendida y aplica
    el rebajo de inventario.

    Soporta:
    - entregas completas;
    - entregas parciales;
    - múltiples preparaciones sobre la misma línea;
    - reintentos sin duplicar el rebajo.

    La cantidad que se rebaja es únicamente:

        cantidad atendida acumulada
        menos
        cantidad ya registrada en WorkOrderLine
    """

    line = (
        WorkOrderRequestLine.query
        .filter(
            WorkOrderRequestLine.id == request_line_id,
        )
        .with_for_update()
        .first()
    )

    if not line:
        raise WorkOrderRequestServiceError(
            "La línea no existe."
        )

    if line.line_status not in {
        "ATENDIDA_PARCIAL",
        "ENTREGADA",
    }:
        raise WorkOrderRequestServiceError(
            "La línea debe estar atendida parcial o totalmente "
            "antes de aplicarla a la OT."
        )

    if line.manager_review_status != "APROBADA":
        raise WorkOrderRequestServiceError(
            "La línea no fue aprobada por jefatura."
        )

    if not line.article:
        raise WorkOrderRequestServiceError(
            "La línea no tiene artículo asociado."
        )

    if _is_tool_article_code(line.article.code):
        raise WorkOrderRequestServiceError(
            "Las herramientas no generan líneas de consumo en la OT. "
            "Deben manejarse como préstamo."
        )

    request_obj = line.work_order_request

    if not request_obj:
        raise WorkOrderRequestServiceError(
            "La línea no tiene una solicitud asociada."
        )

    if not request_obj.sent_to_warehouse_at:
        raise WorkOrderRequestServiceError(
            "La solicitud todavía no fue enviada a bodega."
        )

    work_order = request_obj.work_order

    if not work_order:
        raise WorkOrderRequestServiceError(
            "La solicitud no tiene una OT asociada."
        )

    if not work_order.warehouse_id:
        raise WorkOrderRequestServiceError(
            "La OT no tiene una bodega asignada."
        )

    attended_quantity = Decimal(
        str(line.quantity_attended or 0)
    )

    if attended_quantity <= 0:
        raise WorkOrderRequestServiceError(
            "La línea no tiene cantidad atendida para aplicar."
        )

    # =====================================================
    # CANTIDAD YA REGISTRADA EN LA OT
    # =====================================================

    existing_lines = (
        WorkOrderLine.query
        .filter(
            WorkOrderLine.request_line_id == line.id,
            WorkOrderLine.line_status != "REMOVED",
        )
        .order_by(
            WorkOrderLine.id.asc(),
        )
        .with_for_update()
        .all()
    )

    already_posted_quantity = sum(
        (
            Decimal(str(existing.quantity or 0))
            for existing in existing_lines
            if existing.inventory_posted
        ),
        Decimal("0"),
    )

    quantity_to_post = (
        attended_quantity
        - already_posted_quantity
    )

    # Idempotencia:
    # si la cantidad ya fue aplicada, no vuelve a rebajar inventario.
    if quantity_to_post <= 0:
        if existing_lines:
            return existing_lines[0]

        raise WorkOrderRequestServiceError(
            "No existe cantidad pendiente por aplicar a inventario."
        )

    # =====================================================
    # REBAJO DE INVENTARIO Y KARDEX
    # =====================================================

    try:
        subtract_stock(
            article_id=line.article_id,
            warehouse_id=work_order.warehouse_id,
            quantity=quantity_to_post,
            performed_by_user_id=delivered_by_user_id,
            movement_type="SALIDA_OT",
            reason=(
                f"Salida por OT {work_order.number} "
                f"al preparar pedido en bodega"
            ),
            reference_type="WORK_ORDER",
            reference_id=work_order.id,
            reference_number=work_order.number,
            commit=False,
        )

    except InventoryServiceError as exc:
        raise WorkOrderRequestServiceError(
            str(exc)
        ) from exc

    now = datetime.now(UTC)

    if auto_received:
        effective_received_by_user_id = (
            received_by_user_id
            or delivered_by_user_id
        )
        received_at = now
    else:
        effective_received_by_user_id = (
            received_by_user_id
        )
        received_at = (
            now
            if received_by_user_id
            else None
        )

    # =====================================================
    # CREAR O ACTUALIZAR LA LÍNEA DE LA OT
    # =====================================================

    if existing_lines:
        work_order_line = existing_lines[0]

        work_order_line.quantity = (
            Decimal(
                str(work_order_line.quantity or 0)
            )
            + quantity_to_post
        )

        work_order_line.delivered_by_user_id = (
            delivered_by_user_id
        )

        work_order_line.received_by_user_id = (
            effective_received_by_user_id
        )

        work_order_line.received_at = received_at
        work_order_line.inventory_posted = True
        work_order_line.line_status = "ACTIVE"

        if not work_order_line.notes:
            work_order_line.notes = line.notes

    else:
        work_order_line = WorkOrderLine(
            work_order_id=work_order.id,
            request_line_id=line.id,
            article_id=line.article_id,
            quantity=quantity_to_post,
            delivered_by_user_id=delivered_by_user_id,
            received_by_user_id=(
                effective_received_by_user_id
            ),
            delivered_at=now,
            received_at=received_at,
            line_status="ACTIVE",
            inventory_posted=True,
            notes=(
                line.notes
                or (
                    "Salida aplicada automáticamente "
                    "al preparar el pedido en bodega."
                )
            ),
        )

        db.session.add(work_order_line)

    db.session.flush()

    log_action(
        user_id=(
            effective_received_by_user_id
            or delivered_by_user_id
        ),
        action="CONFIRM_REQUEST_LINE_TO_WORK_ORDER",
        table_name="work_order_lines",
        record_id=str(work_order_line.id),
        details={
            "work_order_id": work_order.id,
            "work_order_number": work_order.number,
            "request_id": request_obj.id,
            "request_line_id": line.id,
            "article_id": line.article_id,
            "article_code": line.article.code,
            "quantity_posted_now": str(
                quantity_to_post
            ),
            "quantity_attended_total": str(
                attended_quantity
            ),
            "quantity_posted_total": str(
                already_posted_quantity
                + quantity_to_post
            ),
            "delivered_by_user_id": (
                delivered_by_user_id
            ),
            "received_by_user_id": (
                effective_received_by_user_id
            ),
            "auto_received": auto_received,
            "warehouse_id": work_order.warehouse_id,
            "inventory_posted": True,
        },
        commit=False,
    )

    if commit:
        db.session.commit()

    return work_order_line