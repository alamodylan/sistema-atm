# app/services/notification_service.py

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_

from app.extensions import db
from app.models.notification import Notification
from app.models.site import Site
from app.models.transfer import Transfer
from app.models.user_site_access import UserSiteAccess
from app.models.warehouse import Warehouse


TRANSFER_ENTITY = "TRANSFER"


def _now():
    return datetime.now(UTC)


def _get_site_name(site_id):
    if not site_id:
        return ""

    site = db.session.get(
        Site,
        int(site_id),
    )

    return site.name if site else ""


def _get_warehouse_name(warehouse_id):
    if not warehouse_id:
        return ""

    warehouse = db.session.get(
        Warehouse,
        int(warehouse_id),
    )

    return warehouse.name if warehouse else ""


def get_users_for_site(site_id):
    """
    Retorna los IDs de usuarios con acceso al predio indicado.
    """
    if not site_id:
        return []

    rows = (
        db.session.query(
            UserSiteAccess.user_id
        )
        .filter(
            UserSiteAccess.site_id == site_id
        )
        .all()
    )

    return [
        row[0]
        for row in rows
    ]


def create_transfer_sent_notifications(transfer):
    """
    Crea una notificación TRANSFER_SENT para cada usuario con acceso
    al predio destino.

    Evita crear notificaciones duplicadas para la combinación:
    usuario + traslado + tipo de notificación.
    """
    if not transfer or not transfer.destination_site_id:
        return 0

    user_ids = get_users_for_site(
        transfer.destination_site_id
    )

    if not user_ids:
        return 0

    origin_site = _get_site_name(
        transfer.origin_site_id
    )

    destination_site = _get_site_name(
        transfer.destination_site_id
    )

    origin_warehouse = _get_warehouse_name(
        transfer.origin_warehouse_id
    )

    destination_warehouse = _get_warehouse_name(
        transfer.destination_warehouse_id
    )

    # =====================================================
    # OBTENER DUPLICADOS EN UNA SOLA CONSULTA
    # =====================================================
    existing_user_ids = {
        row[0]
        for row in (
            db.session.query(
                Notification.recipient_user_id
            )
            .filter(
                Notification.recipient_user_id.in_(
                    user_ids
                ),
                Notification.notification_type
                == "TRANSFER_SENT",
                Notification.entity_type
                == TRANSFER_ENTITY,
                Notification.entity_id
                == transfer.id,
            )
            .all()
        )
    }

    created = 0
    created_at = _now()

    for user_id in user_ids:
        if user_id in existing_user_ids:
            continue

        notification = Notification(
            recipient_user_id=user_id,
            notification_type="TRANSFER_SENT",
            title="Traslado pendiente de recibir",
            message=(
                f"El traslado {transfer.number} fue enviado "
                f"desde {origin_site} / {origin_warehouse} "
                f"hacia {destination_site} / "
                f"{destination_warehouse}. "
                f"Está pendiente de recepción."
            ),
            entity_type=TRANSFER_ENTITY,
            entity_id=transfer.id,
            is_read=False,
            created_at=created_at,
        )

        db.session.add(notification)
        created += 1

    return created


def close_transfer_sent_notifications(transfer):
    """
    Marca como leídas las notificaciones activas TRANSFER_SENT
    cuando el traslado fue recibido.
    """
    if not transfer:
        return 0

    updated = (
        Notification.query
        .filter(
            Notification.notification_type
            == "TRANSFER_SENT",
            Notification.entity_type
            == TRANSFER_ENTITY,
            Notification.entity_id
            == transfer.id,
            Notification.is_read.is_(False),
        )
        .update(
            {
                "is_read": True,
                "read_at": _now(),
            },
            synchronize_session=False,
        )
    )

    return updated


def create_transfer_received_notifications(transfer):
    """
    Crea una notificación de traslado recibido para los usuarios
    con acceso al predio destino.
    """
    if not transfer or not transfer.destination_site_id:
        return 0

    user_ids = get_users_for_site(
        transfer.destination_site_id
    )

    if not user_ids:
        return 0

    destination_site = _get_site_name(
        transfer.destination_site_id
    )

    created = 0
    created_at = _now()

    for user_id in user_ids:
        notification = Notification(
            recipient_user_id=user_id,
            notification_type="TRANSFER_RECEIVED",
            title="Traslado recibido",
            message=(
                f"El traslado {transfer.number} fue recibido "
                f"correctamente en {destination_site}."
            ),
            entity_type=TRANSFER_ENTITY,
            entity_id=transfer.id,
            is_read=False,
            created_at=created_at,
        )

        db.session.add(notification)
        created += 1

    return created


def get_notification_panel_items(
    user_id,
    active_site_id=None,
    limit=20,
):
    """
    Retorna las notificaciones para el panel global.

    Obtiene la transferencia asociada mediante el mismo query,
    evitando una consulta adicional por cada notificación.
    """
    try:
        safe_limit = int(limit or 20)
    except (TypeError, ValueError):
        safe_limit = 20

    safe_limit = max(
        1,
        min(safe_limit, 100),
    )

    query = (
        db.session.query(
            Notification,
            Transfer,
        )
        .outerjoin(
            Transfer,
            and_(
                Notification.entity_type
                == TRANSFER_ENTITY,
                Notification.entity_id
                == Transfer.id,
            ),
        )
        .filter(
            Notification.recipient_user_id
            == user_id
        )
    )

    if active_site_id:
        query = query.filter(
            db.or_(
                Notification.entity_type
                != TRANSFER_ENTITY,
                Transfer.destination_site_id
                == active_site_id,
            )
        )

    rows = (
        query
        .order_by(
            Notification.created_at.desc(),
            Notification.id.desc(),
        )
        .limit(safe_limit)
        .all()
    )

    items = []

    for notification, transfer in rows:
        items.append(
            {
                "id": notification.id,
                "type": notification.notification_type,
                "title": notification.title,
                "message": notification.message,
                "is_read": notification.is_read,
                "created_at": (
                    notification.created_at.isoformat()
                    if notification.created_at
                    else None
                ),
                "entity_type": notification.entity_type,
                "entity_id": notification.entity_id,
                "transfer_number": (
                    transfer.number
                    if transfer
                    else None
                ),
                "transfer_status": (
                    transfer.status
                    if transfer
                    else None
                ),
            }
        )

    return items


def get_popup_notifications(
    user_id,
    active_site_id=None,
):
    """
    Retorna las notificaciones que deben mostrarse como popup.

    Reglas:
    - Solo TRANSFER_SENT.
    - Solo traslados EN_TRANSITO.
    - Solo el predio destino activo, cuando se suministra.
    - Mostrar si nunca se mostró o si pasó una hora.
    - Máximo cinco resultados.
    """
    now = _now()
    popup_limit_time = now - timedelta(
        minutes=60
    )

    query = (
        db.session.query(
            Notification,
            Transfer,
        )
        .join(
            Transfer,
            and_(
                Notification.entity_type
                == TRANSFER_ENTITY,
                Notification.entity_id
                == Transfer.id,
            ),
        )
        .filter(
            Notification.recipient_user_id
            == user_id,
            Notification.notification_type
            == "TRANSFER_SENT",
            Transfer.status
            == "EN_TRANSITO",
            db.or_(
                Notification.last_popup_at.is_(None),
                Notification.last_popup_at
                <= popup_limit_time,
            ),
        )
    )

    if active_site_id:
        query = query.filter(
            Transfer.destination_site_id
            == active_site_id
        )

    rows = (
        query
        .order_by(
            Notification.created_at.asc(),
            Notification.id.asc(),
        )
        .limit(5)
        .all()
    )

    results = []

    for notification, transfer in rows:
        sent_at = (
            transfer.sent_at
            or transfer.created_at
        )

        elapsed_seconds = None

        if sent_at:
            elapsed_seconds = int(
                (now - sent_at).total_seconds()
            )

        results.append(
            {
                "id": notification.id,
                "title": notification.title,
                "message": notification.message,
                "transfer_id": transfer.id,
                "transfer_number": transfer.number,
                "elapsed_seconds": elapsed_seconds,
            }
        )

        notification.last_popup_at = now

    # Solo se confirma una transacción cuando realmente se actualizó
    # al menos una notificación.
    if rows:
        db.session.commit()

    return results


def mark_notification_read(
    notification_id,
    user_id,
):
    notification = (
        Notification.query
        .filter(
            Notification.id
            == notification_id,
            Notification.recipient_user_id
            == user_id,
        )
        .first()
    )

    if not notification:
        return False

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = _now()

        db.session.commit()

    return True