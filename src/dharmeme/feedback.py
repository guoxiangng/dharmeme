"""Thumbs up, thumbs down and Report on pool memes (SPEC.md §4a).

Votes never change how often a meme is shown: every meme appears once per pass of the
pool. They only nudge the order within a pass, by up-rate rather than by count, and only
once a meme has enough votes, so nothing snowballs while the pool is young. A meme is
never hidden automatically: a report, or a poor rating, sends it to the owner to decide.
"""
from datetime import datetime, timedelta, timezone

from .pool import PK as MEME

VOTE = "vote"
KINDS = {"up": "up", "down": "down", "report": "reports"}  # kind -> counter on the meme
MIN_VOTES = 10      # below this a meme counts as unrated
REVIEW_VOTES = 20   # at this many votes...
REVIEW_RATE = 0.3   # ...an up-rate under this sends the meme to the owner
KEEP_DAYS = 90      # how long "this voter already voted on this meme" is remembered


def up_rate(up: int, down: int) -> float | None:
    """Share of thumbs up, or None while there are too few votes to say."""
    total = up + down
    return up / total if total >= MIN_VOTES else None


def weight(meme: dict) -> float:
    """Relative chance in a random pick: 1 for an unrated meme, 0.5 to 1.5 once rated.

    Bounded and based on the rate, so a much-voted meme is not favoured over a new one.
    """
    rate = up_rate(meme.get("up", 0), meme.get("down", 0))
    return 1.0 if rate is None else 0.5 + rate


class Feedback:
    def __init__(self, store, ask_owner=None, now=lambda: datetime.now(timezone.utc)) -> None:
        self.store = store
        self.ask_owner = ask_owner or (lambda meme, reason: None)  # owner's keep/remove prompt
        self.now = now

    def vote(self, voter: str, meme_id: str, kind: str) -> str:
        """Record one vote. Returns "ok", "already" (this voter has voted) or "unknown"."""
        expires = int((self.now() + timedelta(days=KEEP_DAYS)).timestamp())
        # A voter gets one thumb per meme, and separately one report per meme.
        slot = "report" if kind == "report" else "thumb"
        if not self.store.put_new({"pk": VOTE, "sk": f"{voter}#{meme_id}#{slot}",
                                   "expires": expires}):
            return "already"
        item = self.store.add(MEME, meme_id, KINDS[kind])
        if item is None:
            return "unknown"
        up, down = int(item.get("up", 0)), int(item.get("down", 0))
        meme = {"id": meme_id, "template_id": item["template_id"], "slots": item["slots"],
                "lang": item.get("lang", "en")}
        if item["status"] != "approved":
            return "ok"
        if kind == "report" and int(item["reports"]) == 1:
            self.ask_owner(meme, "Reported by a user.")
        elif (kind == "down" and up + down >= REVIEW_VOTES and up / (up + down) < REVIEW_RATE
              and self.store.put_new({"pk": VOTE, "sk": f"review#{meme_id}", "expires": expires})):
            self.ask_owner(meme, f"Rated poorly: {up} up, {down} down.")
        return "ok"
