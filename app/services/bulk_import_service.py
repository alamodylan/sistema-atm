from __future__ import annotations

from app.extensions import db
from app.models.mechanic import Mechanic


def _parse_bool(value) -> bool:
    """
    Convierte valores comunes a booleano.

    Se considera True si viene:
    1, true, si, sí, yes

    Cualquier otro valor se interpreta como False.
    Si viene vacío o None, se toma como True por defecto.
    """
    if value is None:
        return True

    value = str(value).strip().lower()

    if value == "":
        return True

    return value in ("1", "true", "si", "sí", "yes")


def import_mechanics(rows: list[dict]) -> dict:
    """
    Carga masiva de mecánicos.

    Reglas:
    - 'codigo' es la clave única
    - si existe, actualiza
    - si no existe, crea
    - no duplica
    - 'activo' se interpreta como booleano
    """

    created = 0
    updated = 0
    skipped = 0

    for row in rows:
        try:
            code = (row.get("codigo") or "").strip()
            name = (row.get("nombre") or "").strip()
            active_raw = row.get("activo")

            if not code or not name:
                skipped += 1
                continue

            is_active = _parse_bool(active_raw)

            mechanic = Mechanic.query.filter_by(code=code).first()

            if mechanic:
                mechanic.name = name
                mechanic.is_active = is_active
                updated += 1
            else:
                mechanic = Mechanic(
                    code=code,
                    name=name,
                    is_active=is_active,
                )
                db.session.add(mechanic)
                created += 1

        except Exception:
            skipped += 1
            continue

    db.session.commit()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }