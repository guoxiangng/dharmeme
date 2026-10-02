"""Storage for the meme pool and the usage counters — one DynamoDB table, items keyed
by (pk, sk). `MemoryStore` has the same methods, for tests and local runs.
"""
import time


class DynamoStore:
    def __init__(self, table_name: str) -> None:
        import boto3

        self.table = boto3.resource("dynamodb").Table(table_name)

    def items(self, pk: str) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        kwargs = {"KeyConditionExpression": Key("pk").eq(pk)}
        found = []
        while True:
            page = self.table.query(**kwargs)
            found.extend(page["Items"])
            if "LastEvaluatedKey" not in page:
                return found
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def put(self, item: dict) -> None:
        self.table.put_item(Item=item)

    def put_new(self, item: dict) -> bool:
        """Store `item` unless one with its key already exists; False if it does. Atomic."""
        from botocore.exceptions import ClientError

        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def add(self, pk: str, sk: str, field: str) -> dict | None:
        """Add 1 to a number on an existing item and return the item; None if it is gone."""
        from botocore.exceptions import ClientError

        try:
            return self.table.update_item(
                Key={"pk": pk, "sk": sk},
                UpdateExpression="ADD #f :one",
                ConditionExpression="attribute_exists(pk)",
                ExpressionAttributeNames={"#f": field},
                ExpressionAttributeValues={":one": 1},
                ReturnValues="ALL_NEW",
            )["Attributes"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise

    def increment(self, pk: str, sk: str, limit: int, expires: int) -> bool:
        """Add 1 to a counter unless it has reached `limit`; False if it has. Atomic.

        `expires` is the epoch second after which DynamoDB may delete the item (TTL).
        """
        from botocore.exceptions import ClientError

        try:
            self.table.update_item(
                Key={"pk": pk, "sk": sk},
                UpdateExpression="SET #e = :expires ADD #n :one",
                ConditionExpression="attribute_not_exists(#n) OR #n < :limit",
                ExpressionAttributeNames={"#n": "count", "#e": "expires"},
                ExpressionAttributeValues={":one": 1, ":limit": limit, ":expires": expires},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True


class MemoryStore:
    def __init__(self) -> None:
        self.data: dict[tuple[str, str], dict] = {}

    def items(self, pk: str) -> list[dict]:
        return [dict(v) for (p, _), v in sorted(self.data.items()) if p == pk]

    def put(self, item: dict) -> None:
        self.data[(item["pk"], item["sk"])] = dict(item)

    def put_new(self, item: dict) -> bool:
        if (item["pk"], item["sk"]) in self.data:
            return False
        self.put(item)
        return True

    def add(self, pk: str, sk: str, field: str) -> dict | None:
        item = self.data.get((pk, sk))
        if item is None:
            return None
        item[field] = item.get(field, 0) + 1
        return dict(item)

    def increment(self, pk: str, sk: str, limit: int, expires: int) -> bool:
        item = self.data.setdefault((pk, sk), {"pk": pk, "sk": sk, "count": 0})
        if item.get("expires", expires) < time.time():  # what TTL would have deleted
            item["count"] = 0
        if item["count"] >= limit:
            return False
        item["count"] += 1
        item["expires"] = expires
        return True
