from datetime import datetime, time

from flask import Blueprint, flash, render_template, request
from flask_login import login_required
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.audit_service import get_action_label, get_table_label
from app.utils.permissions import permission_required


audit_bp = Blueprint(
    "audit",
    __name__,
    url_prefix="/audit",
)


@audit_bp.route("/", methods=["GET"])
@login_required
@permission_required("auditoria")
def index():
    user_id = request.args.get("user_id", type=int)
    action = request.args.get("action", "", type=str).strip()
    table_name = request.args.get("table_name", "", type=str).strip()
    search = request.args.get("search", "", type=str).strip()
    date_from_raw = request.args.get("date_from", "", type=str).strip()
    date_to_raw = request.args.get("date_to", "", type=str).strip()

    query = AuditLog.query.options(
        joinedload(AuditLog.user)
    )

    if user_id:
        query = query.filter(AuditLog.user_id == user_id)

    if action:
        query = query.filter(AuditLog.action == action)

    if table_name:
        query = query.filter(AuditLog.table_name == table_name)

    if date_from_raw:
        try:
            date_from = datetime.combine(
                datetime.strptime(date_from_raw, "%Y-%m-%d").date(),
                time.min,
            )
            query = query.filter(AuditLog.created_at >= date_from)
        except ValueError:
            flash("La fecha inicial no tiene un formato válido.", "danger")

    if date_to_raw:
        try:
            date_to = datetime.combine(
                datetime.strptime(date_to_raw, "%Y-%m-%d").date(),
                time.max,
            )
            query = query.filter(AuditLog.created_at <= date_to)
        except ValueError:
            flash("La fecha final no tiene un formato válido.", "danger")

    if search:
        like_search = f"%{search}%"

        query = query.filter(
            AuditLog.action.ilike(like_search)
            | AuditLog.table_name.ilike(like_search)
            | AuditLog.record_id.ilike(like_search)
            | AuditLog.details.cast(db.String).ilike(like_search)
        )

    logs = (
        query
        .order_by(
            AuditLog.created_at.desc(),
            AuditLog.id.desc(),
        )
        .limit(500)
        .all()
    )

    users = (
        User.query
        .order_by(User.full_name.asc())
        .all()
    )

    actions = [
        row[0]
        for row in (
            AuditLog.query
            .with_entities(AuditLog.action)
            .distinct()
            .order_by(AuditLog.action.asc())
            .all()
        )
    ]

    tables = [
        row[0]
        for row in (
            AuditLog.query
            .with_entities(AuditLog.table_name)
            .distinct()
            .order_by(AuditLog.table_name.asc())
            .all()
        )
    ]

    enriched_logs = []

    for log in logs:
        details = log.details or {}

        description = details.get("description")
        action_label = (
            details.get("action_label")
            or get_action_label(log.action)
        )
        module_label = (
            details.get("module_label")
            or get_table_label(log.table_name)
        )

        enriched_logs.append(
            {
                "id": log.id,
                "created_at": log.created_at,
                "user": log.user,
                "user_id": log.user_id,
                "action": log.action,
                "action_label": action_label,
                "table_name": log.table_name,
                "module_label": module_label,
                "record_id": log.record_id,
                "description": description,
                "details": details,
            }
        )

    return render_template(
        "audit/index.html",
        logs=enriched_logs,
        users=users,
        actions=actions,
        tables=tables,
        selected_user_id=user_id,
        selected_action=action,
        selected_table_name=table_name,
        search=search,
        date_from=date_from_raw,
        date_to=date_to_raw,
    )