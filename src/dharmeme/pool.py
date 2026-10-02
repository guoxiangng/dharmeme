"""The meme pool — the live list of memes, kept in the store (SPEC.md §4).

The pool in the store is the source of truth. seed/memes.jsonl in the repo only
supplies memes the pool has never seen; it never changes one that is already there.
"""
PK = "meme"
FIELDS = ("id", "template_id", "slots")


class Pool:
    def __init__(self, store) -> None:
        self.store = store

    def approved(self, lang: str = "en") -> list[dict]:
        """The memes Random serves in one language, each with its vote counts.

        A meme without a `lang` is English. Chinese memes are stored once, in
        Traditional characters, and shown in either script.
        """
        return [
            {**{k: item[k] for k in FIELDS},
             "up": int(item.get("up", 0)), "down": int(item.get("down", 0))}
            for item in self.store.items(PK)
            if item["status"] == "approved" and item.get("lang", "en") == lang
        ]

    def all(self) -> list[dict]:
        """Every meme, whatever its status or language."""
        return [{**{k: item[k] for k in (*FIELDS, "status", "created")},
                 "lang": item.get("lang", "en")} for item in self.store.items(PK)]

    def add(self, entry: dict) -> None:
        self.store.put({"pk": PK, "sk": entry["id"], **entry})

    def _update(self, meme_id: str, **changes) -> bool:
        for item in self.store.items(PK):
            if item["sk"] == meme_id:
                self.store.put({**item, **changes})
                return True
        return False

    def set_status(self, meme_id: str, status: str) -> bool:
        """Change one meme's status. False if there is no such meme."""
        return self._update(meme_id, status=status)

    def mark_asked(self, meme_id: str) -> bool:
        """Record that the owner has been sent this meme, so it is never sent twice."""
        return self._update(meme_id, asked=True)

    def unasked_pending(self) -> list[dict]:
        """Pending memes the owner has not been sent yet."""
        return [{**{k: item[k] for k in FIELDS}, "lang": item.get("lang", "en")}
                for item in self.store.items(PK)
                if item["status"] == "pending" and not item.get("asked")]

    def add_missing(self, entries: list[dict]) -> int:
        """Add the `entries` whose id the pool has never seen. Returns how many were added.

        An entry already in the pool is left alone, whatever its status there, so the
        seed can grow without ever undoing a change made to the live pool.
        """
        known = {item["sk"] for item in self.store.items(PK)}
        new = [entry for entry in entries if entry["id"] not in known]
        for entry in new:
            self.add(entry)
        return len(new)
