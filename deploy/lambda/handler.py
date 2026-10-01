"""Lambda entry point. scripts/build_lambda.py puts this file, the dharmeme package,
catalog.json and the seed memes side by side in the deployment folder.
"""
import json
import os
from functools import cache
from pathlib import Path

from dharmeme.api import Api
from dharmeme.limits import Limits
from dharmeme.llm.factory import get_provider
from dharmeme.pool import Pool
from dharmeme.store import DynamoStore

HERE = Path(__file__).parent


@cache
def _api() -> Api:
    store = DynamoStore(os.environ["DHARMEME_TABLE"])
    pool = Pool(store)
    seed = [json.loads(line) for line in
            (HERE / "seed.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    loaded = pool.seed_if_empty(seed)
    if loaded:
        print(f"Seeded the pool with {loaded} memes.")
    limits = Limits(
        store,
        per_ip=int(os.environ.get("DHARMEME_LIMIT_PER_IP", "5")),
        per_day=int(os.environ.get("DHARMEME_LIMIT_PER_DAY", "200")),
        utc_offset=int(os.environ.get("DHARMEME_UTC_OFFSET", "8")),
    )
    templates = json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))
    return Api(pool, limits, cache(get_provider), templates)


def handler(event, context):
    return _api().handle(event)
