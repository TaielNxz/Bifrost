import tempfile
import unittest
from pathlib import Path

from bifrost.manifests import build_manifest, next_version, parse_iso_datetime


class ManifestTests(unittest.TestCase):
    def test_builds_manifest_and_increments_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            archive = Path(temporary_dir) / "world.zip"
            archive.write_bytes(b"world")
            manifest = build_manifest(archive, "Asgard", 1, "Taiel")
            self.assertEqual(manifest["world"], "Asgard")
            self.assertEqual(manifest["version"], 1)
            self.assertEqual(manifest["size"], 5)
            self.assertEqual(next_version(None), 1)
            self.assertEqual(next_version(manifest), 2)
            self.assertIsNotNone(parse_iso_datetime(manifest["uploaded_at"]).tzinfo)


if __name__ == "__main__":
    unittest.main()

