from __future__ import annotations

from typing import Any

from flask import has_request_context, request
from flask_login import current_user

from app.extensions import db
from app.models.audit_log import AuditLog


ACTION_LABELS = {
    "LOGIN": "Inicio de sesión",
    "LOGOUT": "Cierre de sesión",

    "CREATE": "Creó un registro",
    "UPDATE": "Actualizó un registro",
    "DELETE": "Eliminó un registro",
    "PRINT": "Imprimió un documento",
    "EXPORT": "Exportó información",
    "VIEW": "Consultó información",

    "CREATE_WORK_ORDER": "Creó una orden de trabajo",
    "FINALIZE_WORK_ORDER": "Finalizó una orden de trabajo",
    "CLOSE_WORK_ORDER": "Cerró una orden de trabajo",
    "PRINT_WORK_ORDER": "Imprimió una orden de trabajo",

    "CREATE_WORK_ORDER_REQUEST": "Creó una solicitud de artículos",
    "ADD_WORK_ORDER_REQUEST_LINE": "Agregó artículo a una solicitud",
    "SEND_WORK_ORDER_REQUEST": "Envió solicitud a jefatura",
    "SEND_REQUEST_TO_WAREHOUSE": "Envió solicitud a bodega",
    "ATTEND_REQUEST_LINE": "Preparó artículo en bodega",
    "CONFIRM_REQUEST_LINE_TO_WORK_ORDER": "Confirmó entrega de artículo a OT",

    "SUBTRACT_STOCK": "Descontó inventario",
    "ADD_STOCK": "Agregó inventario",
    "ADJUST_STOCK": "Ajustó inventario",
    "CREATE_INVENTORY_ADJUSTMENT": "Creó ajuste manual de inventario",
    "CREATE_PHYSICAL_INVENTORY": "Creó inventario físico",
    "APPLY_PHYSICAL_INVENTORY": "Aplicó ajuste por inventario físico",

    "CREATE_WASTE_ACT": "Creó acta de desecho",
    "ADD_WASTE_ACT_LINE": "Agregó artículo a acta de desecho",
    "PRINT_WASTE_ACT": "Imprimió acta de desecho",

    "CREATE_TRANSFER_REQUEST": "Creó solicitud de traslado",
    "CREATE_TRANSFER": "Creó traslado",
    "SEND_TRANSFER": "Envió traslado",
    "RECEIVE_TRANSFER": "Recibió traslado",

    "CREATE_PURCHASE_REQUEST": "Creó solicitud de compra",
    "CREATE_QUOTATION": "Creó cotización",
    "CREATE_PURCHASE_ORDER": "Creó orden de compra",
    "PRINT_PURCHASE_ORDER": "Imprimió orden de compra",
    "UPDATE_REQUEST_LINE_REQUESTED_QUANTITY": "Actualizó cantidad solicitada",
    "REJECT_REQUEST_LINE_BY_MANAGEMENT": "Solicitud rechazada por jefatura",
    "SEND_REQUEST_TO_WAREHOUSE": "Envió solicitud a bodega",
    "CREATE_TRANSFER_DRAFT_FROM_REQUEST": "Creó traslado (borrador)",
    "SEND_TRANSFER_REQUEST_TO_WAREHOUSE": "Envió solicitud de traslado a bodega",
    "FINALIZE_TRANSFER_REQUEST_REVIEW": "Finalizó revisión de solicitud de traslado",
    "REVIEW_TRANSFER_REQUEST_LINE": "Revisó artículo en solicitud de traslado",
    "SEND_TRANSFER_REQUEST": "Envió solicitud de traslado",
    "ADD_TRANSFER_REQUEST_LINE": "Agregó artículo a solicitud de traslado",

    "CHANGE_WASTE_ACT_STATUS": "Cambió estado de acta de desecho",
    "UPLOAD_WASTE_ACT_SIGNED_PDF": "Subió acta de desecho firmada",
}


TABLE_LABELS = {
    "users": "Usuarios",
    "work_orders": "Órdenes de trabajo",
    "work_order_lines": "Líneas de OT",
    "work_order_requests": "Solicitudes de OT",
    "work_order_request_lines": "Líneas de solicitud OT",
    "warehouse_stock": "Inventario",
    "inventory_ledger": "Kardex",
    "inventory_adjustments": "Ajustes de inventario",
    "inventory_adjustment_lines": "Líneas de ajuste",
    "physical_inventories": "Inventario físico",
    "physical_inventory_lines": "Líneas de inventario físico",
    "waste_acts": "Actas de desecho",
    "waste_act_lines": "Líneas de acta de desecho",
    "transfer_requests": "Solicitudes de traslado",
    "transfers": "Traslados",
    "purchase_requests": "Solicitudes de compra",
    "quotation_batches": "Cotizaciones",
    "purchase_orders": "Órdenes de compra",
    "articles": "Artículos",
    "suppliers": "Proveedores",
    "warehouses": "Bodegas",
}


def get_action_label(action: str) -> str:
    if not action:
        return "-"

    return ACTION_LABELS.get(
        action,
        action.replace("_", " ").capitalize(),
    )


def get_table_label(table_name: str) -> str:
    if not table_name:
        return "-"

    return TABLE_LABELS.get(
        table_name,
        table_name.replace("_", " ").capitalize(),
    )


def _get_request_context() -> dict[str, Any]:
    if not has_request_context():
        return {}

    return {
        "ip_address": request.headers.get("X-Forwarded-For", request.remote_addr),
        "user_agent": request.headers.get("User-Agent"),
        "path": request.path,
        "method": request.method,
    }


def _get_current_user_id() -> int | None:
    try:
        if current_user and current_user.is_authenticated:
            return current_user.id
    except Exception:
        return None

    return None


def log_action(
    *,
    user_id: int | None = None,
    action: str,
    table_name: str,
    record_id: str | int,
    details: dict[str, Any] | None = None,
    description: str | None = None,
    commit: bool = True,
) -> AuditLog:
    """
    Registra un evento de auditoría en el sistema.

    Este log está pensado para registrar acciones importantes como:
    crear, editar, eliminar, imprimir, exportar, consultar, ajustar inventario,
    cerrar OT, enviar solicitudes, preparar artículos, etc.
    """

    if not action or not action.strip():
        raise ValueError("El campo 'action' es obligatorio para auditoría.")

    if not table_name or not table_name.strip():
        raise ValueError("El campo 'table_name' es obligatorio para auditoría.")

    if record_id is None:
        raise ValueError("El campo 'record_id' es obligatorio para auditoría.")

    action = action.strip()
    table_name = table_name.strip()

    clean_details = dict(details) if details else {}

    clean_details.setdefault("action_label", get_action_label(action))
    clean_details.setdefault("module_label", get_table_label(table_name))

    if description:
        clean_details.setdefault("description", description)

    request_context = _get_request_context()
    if request_context:
        clean_details.setdefault("request", request_context)

    if user_id is None:
        user_id = _get_current_user_id()

    log = AuditLog(
        user_id=user_id,
        action=action,
        table_name=table_name,
        record_id=str(record_id),
        details=clean_details,
    )

    db.session.add(log)

    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    return log