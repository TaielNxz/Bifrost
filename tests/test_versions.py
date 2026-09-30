import unittest

from bifrost.versions import archive_current_version, prune_remote_versions


class FakeVersionStorage:
    def __init__(self) -> None:
        self.objects: dict[str, object] = {}
        self.copies: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def get_json(self, key):
        return self.objects.get(key)

    def copy(self, source_key, destination_key):
        self.copies.append((source_key, destination_key))
        self.objects[destination_key] = b"zip"

    def put_json(self, key, value):
        self.objects[key] = value

    def list_keys(self, prefix):
        return [key for key in self.objects if key.startswith(prefix)]

    def delete(self, key):
        self.deleted.append(key)
        del self.objects[key]


def manifest(version: int, sha256: str = "a" * 64) -> dict[str, object]:
    """Construye un manifest remoto mínimo para las pruebas de historial."""
    return {
        "version": version,
        "world": "Asgard",
        "filename": "worlds/Asgard/current/world.zip",
        "size": 100,
        "sha256": sha256,
        "uploaded_by": "Taiel",
        "uploaded_at": "2026-09-30T22:15:00Z",
    }


class RemoteVersionTests(unittest.TestCase):
    def test_archives_zip_before_manifest_and_adjusts_filename(self) -> None:
        storage = FakeVersionStorage()

        created = archive_current_version(storage, "Asgard", manifest(7))  # type: ignore[arg-type]

        self.assertTrue(created)
        self.assertEqual(
            storage.copies,
            [
                (
                    "worlds/Asgard/current/world.zip",
                    "worlds/Asgard/versions/7/world.zip",
                )
            ],
        )
        archived = storage.objects["worlds/Asgard/versions/7/manifest.json"]
        self.assertEqual(archived["filename"], "worlds/Asgard/versions/7/world.zip")

    def test_does_not_overwrite_existing_matching_version(self) -> None:
        storage = FakeVersionStorage()
        storage.objects["worlds/Asgard/versions/7/manifest.json"] = manifest(7)

        created = archive_current_version(storage, "Asgard", manifest(7))  # type: ignore[arg-type]

        self.assertFalse(created)
        self.assertEqual(storage.copies, [])

    def test_rejects_existing_version_with_different_hash(self) -> None:
        storage = FakeVersionStorage()
        storage.objects["worlds/Asgard/versions/7/manifest.json"] = manifest(7, "b" * 64)

        with self.assertRaisesRegex(RuntimeError, "otro hash"):
            archive_current_version(storage, "Asgard", manifest(7))  # type: ignore[arg-type]

    def test_prunes_oldest_versions(self) -> None:
        storage = FakeVersionStorage()
        for version in range(1, 8):
            prefix = f"worlds/Asgard/versions/{version}"
            storage.objects[f"{prefix}/world.zip"] = b"zip"
            storage.objects[f"{prefix}/manifest.json"] = manifest(version)

        removed = prune_remote_versions(storage, "Asgard", keep=5)  # type: ignore[arg-type]

        self.assertEqual(removed, [1, 2])
        self.assertEqual(
            {
                int(key.split("/")[3])
                for key in storage.objects
                if key.startswith("worlds/Asgard/versions/")
            },
            {3, 4, 5, 6, 7},
        )


if __name__ == "__main__":
    unittest.main()
