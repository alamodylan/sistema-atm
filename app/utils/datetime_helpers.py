from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


COSTA_RICA_TZ = ZoneInfo("America/Costa_Rica")


def to_costa_rica_time(value):
    if not value:
        return None

    # Si ya es solo una fecha, se devuelve igual
    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)

    return value.astimezone(COSTA_RICA_TZ)


def format_costa_rica_datetime(
    value,
    fmt="%d/%m/%Y %H:%M",
):
    local_value = to_costa_rica_time(value)

    if not local_value:
        return "-"

    # Si es únicamente una fecha
    if isinstance(local_value, date) and not isinstance(local_value, datetime):
        return local_value.strftime("%d/%m/%Y")

    return local_value.strftime(fmt)