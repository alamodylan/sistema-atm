from __future__ import annotations

from typing import Any

from app.extensions import db
from app.models.audit_log import AuditLog


def log_action(
    *,
    user_id: int | None,
    action: str,
    table_name: str,
    record_id: str | int,
    details: dict[str, Any] | None = None,
    commit: bool = True,
) -> AuditLog:
    """
    Registra un evento de auditoría en el sistema.
    """

    if not action or not action.strip():
        raise ValueError("El campo 'action' es obligatorio para auditoría.")

    if not table_name or not table_name.strip():
        raise ValueError("El campo 'table_name' es obligatorio para auditoría.")

    if record_id is None:
        raise ValueError("El campo 'record_id' es obligatorio para auditoría.")

    log = AuditLog(
        user_id=user_id,
        action=action.strip(),
        table_name=table_name.strip(),
        record_id=str(record_id),
        details=dict(details) if details else {},
    )

    db.session.add(log)

    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    return log