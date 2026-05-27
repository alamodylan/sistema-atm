from flask import Blueprint, jsonify, session
from flask_login import current_user, login_required

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


def _get_active_site_id():
    active_site_id = session.get("active_site_id")
    try:
        return int(active_site_id) if active_site_id else None
    except (TypeError, ValueError):
        return None


@notification_bp.route("/panel", methods=["GET"])
@login_required
def panel():
    items = get_notification_panel_items(
        user_id=current_user.id,
        active_site_id=None,
        limit=20,
    )

    unread_count = sum(
        1 for item in items
        if not item.get("is_read")
    )

    return jsonify({
        "ok": True,
        "unread_count": unread_count,
        "items": items,
    })


@notification_bp.route("/popup-check", methods=["GET"])
@login_required
def popup_check():
    items = get_popup_notifications(
        user_id=current_user.id,
        active_site_id=None,
    )

    return jsonify({
        "ok": True,
        "items": items,
    })


@notification_bp.route("/<int:notification_id>/read", methods=["POST"])
@login_required
def read(notification_id):
    success = mark_notification_read(
        notification_id=notification_id,
        user_id=current_user.id,
    )

    return jsonify({
        "ok": success,
    })