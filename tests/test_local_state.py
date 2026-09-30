import tempfile
import unittest
from pathlib import Path

from bifrost.local_state import STATE_FILENAME, read_base_version, save_base_version


class LocalStateTests(unittest.TestCase):
    def test_saves_multiple_worlds_and_reads_names_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            save_base_version(root, "Asgard", 3, "a" * 64)
            save_base_version(root, "Midgard", 7, "b" * 64)

            self.assertEqual(
                read_base_version(root, "asgard"),
                {"version": 3, "sha256": "a" * 64},
            )
            self.assertEqual(read_base_version(root, "Midgard")["version"], 7)

    def test_rejects_corrupted_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            (root / STATE_FILENAME).write_text("not-json", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "estado local"):
                read_base_version(root, "Asgard")


if __name__ == "__main__":
    unittest.main()
