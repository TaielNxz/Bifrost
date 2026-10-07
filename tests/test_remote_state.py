import unittest

from bifrost.remote_state import commit_world_state, read_world_state, updated_world_state


class FakeStateStorage:
    def __init__(self, state=None, manifest=None, world_lock=None) -> None:
        self.state = state
        self.manifest = manifest
        self.world_lock = world_lock
        self.committed = None
        self.expected_etag = None

    def get_json_with_etag(self, key):
        return self.state, '"etag-1"' if self.state is not None else None

    def get_json(self, key):
        if key.endswith("manifest.json"):
            return self.manifest
        if key.endswith("lock.json"):
            return self.world_lock
        return None

    def put_json_conditional(self, key, value, expected_etag):
        self.committed = value
        self.expected_etag = expected_etag
        return '"etag-2"'


class RemoteStateTests(unittest.TestCase):
    def test_reads_legacy_manifest_as_initial_state(self) -> None:
        manifest = {
            "version": 8, "sha256": "a" * 64, "world": "Asgard",
            "filename": "worlds/Asgard/current/world.zip",
        }
        snapshot = read_world_state(FakeStateStorage(manifest=manifest), "Asgard")  # type: ignore[arg-type]

        self.assertTrue(snapshot.legacy)
        self.assertEqual(snapshot.value["revision"], 8)
        self.assertEqual(snapshot.value["manifest"], manifest)
        self.assertIsNone(snapshot.etag)

    def test_commit_uses_etag_of_snapshot(self) -> None:
        state = {"schema_version": 1, "revision": 3, "manifest": None, "lock": None}
        storage = FakeStateStorage(state=state)
        snapshot = read_world_state(storage, "Asgard")  # type: ignore[arg-type]
        updated = updated_world_state(snapshot, manifest=None, world_lock=None)

        committed = commit_world_state(storage, "Asgard", snapshot, updated)  # type: ignore[arg-type]

        self.assertEqual(storage.expected_etag, '"etag-1"')
        self.assertEqual(storage.committed["revision"], 4)
        self.assertEqual(committed.etag, '"etag-2"')


if __name__ == "__main__":
    unittest.main()
