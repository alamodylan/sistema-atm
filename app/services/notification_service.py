# app/services/notification_service.py

from datetime import datetime, UTC, timedelta

from sqlalchemy import and_

from app.extensions import db
from app.models.notification import Notification
from app.models.user_site_access import UserSiteAccess
from app.models.transfer import Transfer
from app.models.site import Site
from app.models.warehouse import Warehouse


TRANSFER_ENTITY = "TRANSFER"


def _now():
    return datetime.now(UTC)


def _get_site_name(site_id):
    if not site_id:
        return ""
    site = Site.query.get(site_id)
    return site.name if site else ""


def _get_warehouse_name(warehouse_id):
    if not warehouse_id:
        return ""
    warehouse = Warehouse.query.get(warehouse_id)
    return warehouse.name if warehouse else ""


def get_users_for_site(site_id):
    """
    Retorna IDs de usuarios que tienen acceso al predio indicado.
    """
    rows = (
        db.session.query(UserSiteAccess.user_id)
        .filter(UserSiteAccess.site_id == site_id)
        .all()
    )
    return [r[0] for r in rows]


def create_transfer_sent_notifications(transfer):
    """
    Crea una notificación TRANSFER_SENT para cada usuario con acceso
    al predio destino del traslado.

    No duplica notificaciones para el mismo usuario/traslado.
    """
    if not transfer or not transfer.destination_site_id:
        return 0

    user_ids = get_users_for_site(transfer.destination_site_id)

    if not user_ids:
        return 0

    origin_site = _get_site_name(transfer.origin_site_id)
    destination_site = _get_site_name(transfer.destination_site_id)

    origin_warehouse = _get_warehouse_name(transfer.origin_warehouse_id)
    destination_warehouse = _get_warehouse_name(transfer.destination_warehouse_id)

    created = 0

    for user_id in user_ids:
        exists = (
            Notification.query
            .filter(
                Notification.recipient_user_id == user_id,
                Notification.notification_type == "TRANSFER_SENT",
                Notification.entity_type == TRANSFER_ENTITY,
                Notification.entity_id == transfer.id,
            )
            .first()
        )

        if exists:
            continue

        notification = Notification(
            recipient_user_id=user_id,
            notification_type="TRANSFER_SENT",
            title="Traslado pendiente de recibir",
            message=(
                f"El traslado {transfer.number} fue enviado "
                f"desde {origin_site} / {origin_warehouse} "
                f"hacia {destination_site} / {destination_warehouse}. "
                f"Está pendiente de recepción."
            ),
            entity_type=TRANSFER_ENTITY,
            entity_id=transfer.id,
            is_read=False,
            created_at=_now(),
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

    now = _now()

    updated = (
        Notification.query
        .filter(
            Notification.notification_type == "TRANSFER_SENT",
            Notification.entity_type == TRANSFER_ENTITY,
            Notification.entity_id == transfer.id,
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

    return updated


def create_transfer_received_notifications(transfer):
    """
    Crea notificación de traslado recibido para usuarios del predio destino.
    """
    if not transfer or not transfer.destination_site_id:
        return 0

    user_ids = get_users_for_site(transfer.destination_site_id)

    if not user_ids:
        return 0

    destination_site = _get_site_name(transfer.destination_site_id)

    created = 0

    for user_id in user_ids:
        notification = Notification(
            recipient_user_id=user_id,
            notification_type="TRANSFER_RECEIVED",
            title="Traslado recibido",
            message=(
                f"El traslado {transfer.number} fue recibido correctamente "
                f"en {destination_site}."
            ),
            entity_type=TRANSFER_ENTITY,
            entity_id=transfer.id,
            is_read=False,
            created_at=_now(),
        )

        db.session.add(notification)
        created += 1

    return created


def get_notification_panel_items(user_id, active_site_id=None, limit=20):
    """
    Retorna notificaciones para panel global.

    Si active_site_id viene informado, valida que las notificaciones
    de traslados pertenezcan al predio destino activo.
    """
    query = (
        Notification.query
        .filter(Notification.recipient_user_id == user_id)
        .order_by(Notification.created_at.desc())
    )

    if active_site_id:
        query = (
            query
            .outerjoin(
                Transfer,
                and_(
                    Notification.entity_type == TRANSFER_ENTITY,
                    Notification.entity_id == Transfer.id,
                ),
            )
            .filter(
                db.or_(
                    Notification.entity_type != TRANSFER_ENTITY,
                    Transfer.destination_site_id == active_site_id,
                )
            )
        )

    notifications = query.limit(limit).all()

    items = []

    for n in notifications:
        transfer = None

        if n.entity_type == TRANSFER_ENTITY and n.entity_id:
            transfer = Transfer.query.get(n.entity_id)

        items.append(
            {
                "id": n.id,
                "type": n.notification_type,
                "title": n.title,
                "message": n.message,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "entity_type": n.entity_type,
                "entity_id": n.entity_id,
                "transfer_number": transfer.number if transfer else None,
                "transfer_status": transfer.status if transfer else None,
            }
        )

    return items


def get_popup_notifications(user_id, active_site_id=None):
    """
    Retorna notificaciones que deben mostrarse como popup.

    Regla:
    - Solo TRANSFER_SENT
    - Solo no leídas
    - Solo traslados EN_TRANSITO
    - Solo predio destino activo si aplica
    - Mostrar si nunca se mostró o si pasaron 2 horas
    """
    now = _now()
    popup_limit_time = now - timedelta(minutes=4)

    query = (
        Notification.query
        .join(
            Transfer,
            and_(
                Notification.entity_type == TRANSFER_ENTITY,
                Notification.entity_id == Transfer.id,
            ),
        )
        .filter(
            Notification.recipient_user_id == user_id,
            Notification.notification_type == "TRANSFER_SENT",
            Notification.is_read.is_(False),
            Transfer.status == "EN_TRANSITO",
            db.or_(
                Notification.last_popup_at.is_(None),
                Notification.last_popup_at <= popup_limit_time,
            ),
        )
    )

    if active_site_id:
        query = query.filter(Transfer.destination_site_id == active_site_id)

    notifications = query.order_by(Notification.created_at.asc()).limit(5).all()

    results = []

    for n in notifications:
        transfer = Transfer.query.get(n.entity_id)

        if not transfer:
            continue

        sent_at = transfer.sent_at or transfer.created_at
        elapsed_seconds = None

        if sent_at:
            elapsed_seconds = int((now - sent_at).total_seconds())

        results.append(
            {
                "id": n.id,
                "title": n.title,
                "message": n.message,
                "transfer_id": transfer.id,
                "transfer_number": transfer.number,
                "elapsed_seconds": elapsed_seconds,
            }
        )

        n.last_popup_at = now

    db.session.commit()

    return results


def mark_notification_read(notification_id, user_id):
    notification = (
        Notification.query
        .filter(
            Notification.id == notification_id,
            Notification.recipient_user_id == user_id,
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