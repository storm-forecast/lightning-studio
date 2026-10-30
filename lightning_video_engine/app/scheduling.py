"""Calendar-aligned slots: 00, 02, ... 22 in the configured time zone."""
from datetime import datetime
from zoneinfo import ZoneInfo


def interval_slot(now: datetime, hours=2, timezone='America/Belem'):
    if hours<1 or hours>24 or 24%hours:
        raise ValueError('o intervalo em horas deve dividir 24')
    if now.tzinfo is None:raise ValueError('data sem fuso')
    local=now.astimezone(ZoneInfo(timezone))
    slot=local.replace(hour=(local.hour//hours)*hours,minute=0,second=0,microsecond=0)
    return f'{timezone}:{hours}h:{slot.isoformat()}',slot
