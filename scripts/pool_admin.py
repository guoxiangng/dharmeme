"""Look at and tidy the live meme pool in DynamoDB.

    python scripts/pool_admin.py report            # counts by language and status
    python scripts/pool_admin.py write-seed        # seed/memes.jsonl = the approved English pool
    python scripts/pool_admin.py delete-rejected   # remove rejected memes for good

Needs AWS credentials and `pip install -e ".[aws]"`. The table is found from the SAM
stack's outputs (stack "dharmeme", region ap-southeast-1; override with --stack/--region).

Do not run write-seed or delete-rejected while the owner is approving memes in Telegram.
Run write-seed (and deploy) BEFORE delete-rejected: a deleted meme that is still in the
seed would be added back as approved on the Lambda's next cold start.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "seed" / "memes.jsonl"


def table_for(stack: str, region: str):
    outputs = boto3.client("cloudformation", region_name=region).describe_stacks(
        StackName=stack)["Stacks"][0]["Outputs"]
    name = next(o["OutputValue"] for o in outputs if o["OutputKey"] == "TableName")
    return boto3.resource("dynamodb", region_name=region).Table(name)


def memes(table) -> list[dict]:
    items, kwargs = [], {"KeyConditionExpression": Key("pk").eq("meme")}
    while True:
        page = table.query(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["report", "write-seed", "delete-rejected"])
    parser.add_argument("--stack", default="dharmeme")
    parser.add_argument("--region", default="ap-southeast-1")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    table = table_for(args.stack, args.region)
    items = memes(table)
    for (lang, status), n in sorted(Counter(
            (i.get("lang", "en"), i["status"]) for i in items).items()):
        print(f"{lang:8} {status:9} {n}")

    if args.action == "report":
        english = [i for i in items if i["status"] == "approved" and i.get("lang", "en") == "en"]
        per_template = Counter(i["template_id"] for i in english)
        print("approved English memes per template:", dict(sorted(per_template.items())))

    if args.action == "write-seed":
        # The seed is what the site bundles as its offline fallback: English, approved.
        approved = sorted((i for i in items if i["status"] == "approved"
                           and i.get("lang", "en") == "en"), key=lambda i: i["sk"])
        lines = [json.dumps({"id": i["sk"], "template_id": i["template_id"],
                             "slots": dict(i["slots"]), "status": "approved",
                             "created": i["created"]}, ensure_ascii=False) for i in approved]
        SEED.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print(f"seed now holds {len(lines)} approved English memes; commit and deploy it")

    if args.action == "delete-rejected":
        rejected = [i for i in items if i["status"] == "rejected"]
        seed_ids = {json.loads(line)["id"] for line in
                    SEED.read_text(encoding="utf-8").splitlines() if line.strip()}
        clash = [i["sk"] for i in rejected if i["sk"] in seed_ids]
        if clash:
            sys.exit(f"refusing: still in the seed, so they would be re-added: {clash}\n"
                     "run write-seed and deploy first")
        with table.batch_writer() as batch:
            for i in rejected:
                batch.delete_item(Key={"pk": "meme", "sk": i["sk"]})
        print(f"deleted {len(rejected)} rejected memes")


if __name__ == "__main__":
    main()
