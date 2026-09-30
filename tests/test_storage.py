import unittest
from pathlib import Path

from botocore.exceptions import ClientError

from bifrost.config import Settings
from bifrost.storage import ConcurrentUpdateError, R2Storage


class FakeClient:
    def __init__(self, error: ClientError | None = None) -> None:
        self.error = error
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"ETag": '"new-etag"'}


class ConditionalStorageTests(unittest.TestCase):
    def make_storage(self, client: FakeClient) -> R2Storage:
        """Construye un storage aislado con un cliente S3 falso."""
        settings = Settings("url", "id", "secret", "bucket", Path("."), "Taiel")
        return R2Storage(settings, client=client)

    def test_conditional_create_uses_if_none_match(self) -> None:
        client = FakeClient()
        storage = self.make_storage(client)

        etag = storage.put_json_conditional("state.json", {"revision": 1}, None)

        self.assertEqual(etag, '"new-etag"')
        self.assertEqual(client.calls[0]["IfNoneMatch"], "*")
        self.assertNotIn("IfMatch", client.calls[0])

    def test_conditional_update_uses_if_match(self) -> None:
        client = FakeClient()
        storage = self.make_storage(client)

        storage.put_json_conditional("state.json", {"revision": 2}, '"old-etag"')

        self.assertEqual(client.calls[0]["IfMatch"], '"old-etag"')
        self.assertNotIn("IfNoneMatch", client.calls[0])

    def test_precondition_failure_becomes_concurrent_update(self) -> None:
        error = ClientError(
            {
                "Error": {"Code": "PreconditionFailed", "Message": "conflict"},
                "ResponseMetadata": {"HTTPStatusCode": 412},
            },
            "PutObject",
        )
        storage = self.make_storage(FakeClient(error))

        with self.assertRaises(ConcurrentUpdateError):
            storage.put_json_conditional("state.json", {"revision": 2}, '"old"')


if __name__ == "__main__":
    unittest.main()
