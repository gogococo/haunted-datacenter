from email.utils import parsedate_to_datetime
from datetime import timezone

def retry_after(value, now):
    if not isinstance(value, str):
        return 60
    value = value.strip()
    if value.isascii() and value.isdecimal():
        return int(value)
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return 60
        return max(0, (date - now).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return 60
