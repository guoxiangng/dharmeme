"""Usage limits for the prompt feature (SPEC.md §7): a per-IP daily limit and a global
daily cap. The global cap is the real ceiling on cost; IPs are easy to change.
"""
from datetime import datetime, timedelta, timezone

PK = "usage"
KEEP_DAYS = 2  # counters delete themselves (TTL) after this


class Limits:
    def __init__(self, store, per_ip: int = 5, per_day: int = 200, utc_offset: int = 8,
                 now=lambda: datetime.now(timezone.utc), alert=None) -> None:
        self.store = store
        self.alert = alert  # alert(reason, ip, who): the owner is told, once a day per kind
        self.per_ip = per_ip
        self.per_day = per_day
        self.tz = timezone(timedelta(hours=utc_offset))  # the day rolls over in local time
        self.now = now

    def allow_vote(self, voter: str, per_day: int = 300) -> bool:
        """Count one vote against the voter's daily allowance. Votes cost no LLM call;
        this only stops a script from writing to the table without end."""
        now = self.now().astimezone(self.tz)
        expires = int((now + timedelta(days=KEEP_DAYS)).timestamp())
        return self.store.increment(PK, f"votes#{voter}#{now:%Y-%m-%d}", per_day, expires)

    def check(self, ip: str, who: str = "") -> str | None:
        """Count one request against both limits. None if it may go ahead; otherwise
        "limit" (this visitor's own) or "cap" (everyone's, for the day).

        The IP is checked first so one visitor hitting their own limit doesn't eat into
        the global cap. The first refusal of each kind in a day is passed to `alert`,
        with `who` (a readable name for the visitor, if known), so the owner hears of it
        once rather than on every refused request.
        """
        now = self.now().astimezone(self.tz)
        day = now.strftime("%Y-%m-%d")
        expires = int((now + timedelta(days=KEEP_DAYS)).timestamp())
        if not self.store.increment(PK, f"ip#{ip}#{day}", self.per_ip, expires):
            reason, key = "limit", f"alerted#{ip}#{day}"
        elif not self.store.increment(PK, f"global#{day}", self.per_day, expires):
            reason, key = "cap", f"alerted#global#{day}"
        else:
            return None
        if self.alert is not None and self.store.increment(PK, key, 1, expires):
            try:
                self.alert(reason, ip, who)
            except Exception as exc:  # noqa: BLE001 — an alert never blocks the visitor
                print(f"limits: alert failed: {exc!r}")
        return reason

    def allow(self, ip: str, who: str = "") -> bool:
        return self.check(ip, who) is None
