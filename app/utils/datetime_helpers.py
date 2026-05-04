from datetime import UTC
from zoneinfo import ZoneInfo


COSTA_RICA_TZ = ZoneInfo("America/Costa_Rica")


def to_costa_rica_time(value):
    if not value:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)

    return value.astimezone(COSTA_RICA_TZ)


def format_costa_rica_datetime(value, fmt="%d/%m/%Y %H:%M"):
    local_value = to_costa_rica_time(value)

    if not local_value:
        return "-"

    return local_value.strftime(fmt)