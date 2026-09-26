import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bifrost.cli import push_menu
from bifrost.config import Settings


class FakeStorage:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.manifest = None

    def read_manifest(self, world_name):
        return None

    def upload_file(self, local_path, key):
        self.events.append("zip")

    def write_manifest(self, world_name, manifest):
        self.events.append("manifest")
        self.manifest = manifest

    def read_lock(self, world_name):
        return None


class SyncFlowTests(unittest.TestCase):
    def test_push_publishes_zip_before_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            world = root / "Asgard"
            world.mkdir()
            (world / "save.db2").write_bytes(b"save")
            settings = Settings("url", "id", "secret", "bucket", root, "Taiel")
            storage = FakeStorage()
            with patch("builtins.input", side_effect=["1", "s"]):
                push_menu(settings, storage)  # type: ignore[arg-type]
            self.assertEqual(storage.events, ["zip", "manifest"])
            self.assertEqual(storage.manifest["uploaded_by"], "Taiel")


if __name__ == "__main__":
    unittest.main()
