import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from bifrost.cli import pull_menu, push_menu
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
            output = io.StringIO()
            with redirect_stdout(output), patch("builtins.input", side_effect=["1", "s"]):
                push_menu(settings, storage)  # type: ignore[arg-type]
            self.assertEqual(storage.events, ["zip", "manifest"])
            self.assertEqual(storage.manifest["uploaded_by"], "Taiel")
            self.assertIn("Asgard          (4 bytes,", output.getvalue())
            self.assertRegex(output.getvalue(), r"Subiendo ZIP de \d+(?:\.\d)? (?:bytes|KB)\.\.\.")

    def test_pull_list_displays_manifest_size_in_readable_format(self) -> None:
        class PullStorage:
            def list_worlds(self):
                return ["Asgard"]

            def read_manifest(self, world_name):
                return {
                    "version": 12,
                    "size": 88_709_530,
                    "uploaded_at": "2026-09-30T22:15:00Z",
                    "uploaded_by": "Taiel",
                }

        settings = Settings("url", "id", "secret", "bucket", Path("."), "Taiel")
        output = io.StringIO()
        with redirect_stdout(output), patch("builtins.input", return_value="0"):
            pull_menu(settings, PullStorage())  # type: ignore[arg-type]

        self.assertIn("versión 12, 84.6 MB,", output.getvalue())


if __name__ == "__main__":
    unittest.main()
