import tempfile
import unittest
import zipfile
from pathlib import Path

from bifrost.archives import create_zip, extract_zip, verify_zip


class ArchiveTests(unittest.TestCase):
    def test_round_trip_preserves_paths_and_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "source"
            (source / "subdir").mkdir(parents=True)
            (source / "world.fwl2").write_bytes(b"metadata")
            (source / "subdir" / "world.db2").write_bytes(b"database")

            archive = create_zip(source, root / "world.zip")
            destination = extract_zip(archive, root / "restored")

            self.assertEqual((destination / "world.fwl2").read_bytes(), b"metadata")
            self.assertEqual((destination / "subdir" / "world.db2").read_bytes(), b"database")
            self.assertTrue(verify_zip(archive, __import__("hashlib").sha256(archive.read_bytes()).hexdigest()))

    def test_extract_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            archive = root / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as file:
                file.writestr("../escape.txt", "no")
            with self.assertRaises(ValueError):
                extract_zip(archive, root / "destination")


if __name__ == "__main__":
    unittest.main()

