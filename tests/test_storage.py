import unittest
from pathlib import Path
from unittest.mock import Mock

from botocore.exceptions import ClientError, EndpointConnectionError

from bifrost.config import Settings
from bifrost.storage import ConcurrentUpdateError, R2Storage
from bifrost.world_names import InvalidWorldNameError, WorldNameConflictError


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


class WorldListingStorageTests(unittest.TestCase):
    def make_storage(self, pages) -> tuple[R2Storage, Mock]:
        """Prepara un cliente falso con páginas de prefijos, sin conectar con R2."""
        client = Mock()
        client.get_paginator.return_value.paginate.return_value = iter(pages)
        settings = Settings("url", "id", "secret", "bucket", Path("."), "Taiel")
        return R2Storage(settings, client=client), client

    def test_lists_all_pages_and_preserves_valid_names(self) -> None:
        storage, client = self.make_storage([
            {"CommonPrefixes": [{"Prefix": "worlds/Peña del Dragón/"}]},
            {},
            {"CommonPrefixes": [{"Prefix": "worlds/Bifröst/"}]},
        ])
        errors = []
        self.assertEqual(storage.list_worlds(errors=errors), ["Bifröst", "Peña del Dragón"])
        self.assertEqual(errors, [])
        client.get_paginator.assert_called_once_with("list_objects_v2")
        client.get_paginator.return_value.paginate.assert_called_once_with(
            Bucket="bucket", Prefix="worlds/", Delimiter="/"
        )
        client.get_object.assert_not_called()
        client.put_object.assert_not_called()

    def test_detects_conflicts_between_pages_and_keeps_other_worlds(self) -> None:
        storage, _ = self.make_storage([
            {"CommonPrefixes": [{"Prefix": "worlds/Asgard/"}, {"Prefix": "worlds/Bifröst/"}]},
            {"CommonPrefixes": [{"Prefix": "worlds/asgard/"}, {"Prefix": "worlds/NUL/"}]},
        ])
        errors = []
        self.assertEqual(storage.list_worlds(errors=errors), ["Bifröst"])
        self.assertEqual(len(errors), 2)
        self.assertIsInstance(errors[0], InvalidWorldNameError)
        self.assertEqual(errors[0].name, "NUL")
        self.assertIsInstance(errors[1], WorldNameConflictError)
        self.assertEqual(errors[1].names, ("Asgard", "asgard"))

    def test_rejects_unsafe_components_without_trimming_or_reinterpreting_prefixes(self) -> None:
        prefixes = [
            "worlds//", "worlds/../", "worlds/Mundo./", "worlds/Asgard /",
            "worlds/Asgard//", "worlds/Asgard/copia/", "worlds/Mundo\\copia/",
            "worlds/NUL.txt/", "worlds/Mundo\n/", "worlds/C:Asgard/",
            "other/Asgard/", "worlds/Asgard", None,
        ]
        storage, _ = self.make_storage([{
            "CommonPrefixes": [{"Prefix": prefix} for prefix in [*prefixes, "worlds/Bifröst/"]]
        }])
        errors = []
        self.assertEqual(storage.list_worlds(errors=errors), ["Bifröst"])
        self.assertEqual(len(errors), len(prefixes))
        rejected = {error.name for error in errors}
        self.assertIn("", rejected)
        self.assertIn("Asgard/", rejected)
        self.assertIn("Asgard/copia", rejected)
        self.assertIn("other/Asgard/", rejected)

    def test_exact_repeated_prefix_is_not_a_case_conflict(self) -> None:
        storage, _ = self.make_storage([
            {"CommonPrefixes": [{"Prefix": "worlds/Asgard/"}]},
            {"CommonPrefixes": [{"Prefix": "worlds/Asgard/"}]},
        ])
        errors = []
        self.assertEqual(storage.list_worlds(errors=errors), ["Asgard"])
        self.assertEqual(errors, [])

    def test_empty_listing(self) -> None:
        storage, _ = self.make_storage([{}])
        self.assertEqual(storage.list_worlds(), [])

    def test_listing_errors_propagate_instead_of_becoming_an_empty_list(self) -> None:
        for code in ("AccessDenied", "NoSuchBucket", "InternalError"):
            with self.subTest(code=code):
                storage, client = self.make_storage([])
                error = ClientError({"Error": {"Code": code}}, "ListObjectsV2")
                client.get_paginator.return_value.paginate.side_effect = error
                with self.assertRaises(ClientError) as caught:
                    storage.list_worlds()
                self.assertIs(caught.exception, error)

    def test_failure_on_a_later_page_does_not_return_a_partial_listing(self) -> None:
        storage, client = self.make_storage([])
        error = EndpointConnectionError(endpoint_url="https://example.invalid")

        def interrupted_pages():
            """Simula un fallo de red después de recibir una primera página incompleta."""
            yield {"CommonPrefixes": [{"Prefix": "worlds/Asgard/"}, {"Prefix": "worlds/NUL/"}]}
            raise error

        client.get_paginator.return_value.paginate.return_value = interrupted_pages()
        errors = []
        with self.assertRaises(EndpointConnectionError) as caught:
            storage.list_worlds(errors=errors)
        self.assertIs(caught.exception, error)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
