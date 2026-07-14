from datetime import UTC, datetime

from flask import Blueprint, jsonify, session
from flask_login import current_user, login_required

from app.extensions import db
from app.models.notification import Notification
from app.services.notification_service import (
    get_notification_panel_items,
    get_popup_notifications,
    mark_notification_read,
)


notification_bp = Blueprint(
    "notifications",
    __name__,
    url_prefix="/notifications",
)


def _get_active_site_id() -> int | None:
    """
    Retorna el ID del predio activo almacenado en la sesión.

    Si el valor no existe o no es válido, retorna None.
    """
    active_site_id = session.get("active_site_id")

    if active_site_id is None:
        return None

    try:
        return int(active_site_id)
    except (TypeError, ValueError):
        return None


# =========================================================
# PANEL DE NOTIFICACIONES
# =========================================================
@notification_bp.route("/panel", methods=["GET"])
@login_required
def panel():
    active_site_id = _get_active_site_id()

    items = get_notification_panel_items(
        user_id=current_user.id,
        active_site_id=active_site_id,
        limit=20,
    )

    unread_count = sum(
        1
        for item in items
        if not item.get("is_read")
    )

    return jsonify(
        {
            "ok": True,
            "unread_count": unread_count,
            "items": items,
        }
    )


# =========================================================
# COMPROBAR NOTIFICACIONES POPUP
# =========================================================
@notification_bp.route(
    "/popup-check",
    methods=["GET"],
)
@login_required
def popup_check():
    active_site_id = _get_active_site_id()

    items = get_popup_notifications(
        user_id=current_user.id,
        active_site_id=active_site_id,
    )

    return jsonify(
        {
            "ok": True,
            "items": items,
        }
    )


# =========================================================
# MARCAR UNA NOTIFICACIÓN COMO LEÍDA
# =========================================================
@notification_bp.route(
    "/<int:notification_id>/read",
    methods=["POST"],
)
@login_required
def read(notification_id: int):
    success = mark_notification_read(
        notification_id=notification_id,
        user_id=current_user.id,
    )

    return jsonify(
        {
            "ok": success,
        }
    )


# =========================================================
# MARCAR TODAS LAS NOTIFICACIONES COMO LEÍDAS
# =========================================================
@notification_bp.route(
    "/mark-all-read",
    methods=["POST"],
)
@login_required
def mark_all_read():
    now = datetime.now(UTC)

    updated_count = (
        Notification.query
        .filter(
            Notification.recipient_user_id
            == current_user.id,
            Notification.is_read.is_(False),
        )
        .update(
            {
                "is_read": True,
                "read_at": now,
            },
            synchronize_session=False,
        )
    )

    db.session.commit()

    return jsonify(
        {
            "ok": True,
            "updated_count": updated_count,
        }
    )