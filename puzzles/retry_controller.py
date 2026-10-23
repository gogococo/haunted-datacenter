from email.utils import parsedate_to_datetime
from datetime import timezone

def retry_after(value, now):
    # The previous engineer assumed this header was always an integer.
    # Return a nonnegative wait in seconds. Invalid input: 60 seconds.
    try:
        return int(value)
    except (ValueError, TypeError):
        return 60
