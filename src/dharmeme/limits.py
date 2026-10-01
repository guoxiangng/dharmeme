"""Usage limits for the prompt feature (SPEC.md §7): a per-IP daily limit and a global
daily cap. The global cap is the real ceiling on cost; IPs are easy to change.
"""
from datetime import datetime, timedelta, timezone

PK = "usage"
KEEP_DAYS = 2  # counters delete themselves (TTL) after this


class Limits:
    def __init__(self, store, per_ip: int = 5, per_day: int = 200, utc_offset: int = 8,
                 now=lambda: datetime.now(timezone.utc)) -> None:
        self.store = store
        self.per_ip = per_ip
        self.per_day = per_day
        self.tz = timezone(timedelta(hours=utc_offset))  # the day rolls over in local time
        self.now = now

    def allow(self, ip: str) -> bool:
        """Count one request against both limits. False if either is used up.

        The IP is checked first so one visitor hitting their own limit doesn't eat into
        the global cap.
        """
        now = self.now().astimezone(self.tz)
        day = now.strftime("%Y-%m-%d")
        expires = int((now + timedelta(days=KEEP_DAYS)).timestamp())
        return self.store.increment(PK, f"ip#{ip}#{day}", self.per_ip, expires) and (
            self.store.increment(PK, f"global#{day}", self.per_day, expires)
        )
