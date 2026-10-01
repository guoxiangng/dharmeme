"""The meme pool — the live list of memes, kept in the store (SPEC.md §4).

The pool in the store is the source of truth. seed/memes.jsonl in the repo is only
loaded into an empty pool; after that it is never read again.
"""
PK = "meme"
FIELDS = ("id", "template_id", "slots")


class Pool:
    def __init__(self, store) -> None:
        self.store = store

    def approved(self) -> list[dict]:
        return [
            {k: item[k] for k in FIELDS}
            for item in self.store.items(PK)
            if item["status"] == "approved"
        ]

    def add(self, entry: dict) -> None:
        self.store.put({"pk": PK, "sk": entry["id"], **entry})

    def seed_if_empty(self, entries: list[dict]) -> int:
        """Load `entries` into an empty pool. Returns how many were loaded."""
        if self.store.items(PK):
            return 0
        for entry in entries:
            self.add(entry)
        return len(entries)
