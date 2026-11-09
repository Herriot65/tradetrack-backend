"""Wall-clock schedules, anchored to the user's date and IANA timezone."""
import calendar
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def next_occurrence(task, after):
    zone = ZoneInfo(task.timezone)
    anchor = task.start_date
    today = after.astimezone(zone).date()
    if task.frequency == "once":
        dates = [anchor]
    elif task.frequency == "monthly":
        year, month = max((anchor.year, anchor.month), (today.year, today.month))
        dates = []
        for offset in range(3):
            index = year * 12 + month - 1 + offset
            y, m = divmod(index, 12)
            m += 1
            dates.append(anchor.replace(year=y, month=m, day=min(anchor.day, calendar.monthrange(y, m)[1])))
    else:
        step = 7 if task.frequency == "weekly" else 1
        delta = max(0, (today - anchor).days)
        start = anchor + timedelta(days=(delta // step) * step)
        dates = [start + timedelta(days=step * offset) for offset in range(3)]
    for date in dates:
        candidate = datetime.combine(date, task.local_time, zone).astimezone(timezone.utc)
        # Normalize nonexistent local times forward through the DST gap; choose
        # the first occurrence during a repeated hour, avoiding duplicate runs.
        if date >= anchor and candidate > after:
            return candidate
    return None
