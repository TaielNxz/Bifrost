import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from bifrost.cli import copy_menu, lock_menu, pull_menu, push_menu, status_menu
from bifrost.config import Settings
from bifrost.remote_state import StateSnapshot
from bifrost.storage import R2Storage


class WorldNameMenuTests(unittest.TestCase):
    def make_storage(self, names: list[str]) -> tuple[R2Storage, Mock]:
        """Prepara prefijos remotos en un cliente falso sin consultar R2."""
        client = Mock()
        client.get_paginator.return_value.paginate.return_value = [{
            "CommonPrefixes": [{"Prefix": f"worlds/{name}/"} for name in names]
        }]
        settings = Settings("url", "id", "secret", "bucket", Path("."), "Taiel")
        return R2Storage(settings, client=client), client

    def make_snapshot(self, name: str) -> StateSnapshot:
        """Construye metadata falsa suficiente para presentar un mundo libre."""
        return StateSnapshot({
            "schema_version": 1,
            "revision": 1,
            "manifest": {
                "version": 1,
                "world": name,
                "filename": f"worlds/{name}/current/world.zip",
                "size": 10,
                "sha256": "a" * 64,
                "uploaded_at": "2020-01-01T00:00:00Z",
                "uploaded_by": "Jugador",
            },
            "lock": None,
        }, None)

    def test_remote_menus_report_rejections_and_only_read_valid_worlds(self) -> None:
        for menu in (status_menu, pull_menu, copy_menu, lock_menu):
            with self.subTest(menu=menu.__name__):
                name = "Peña del Dragón"
                storage, client = self.make_storage(["Asgard", "asgard", "NUL", name])
                settings = Settings("url", "id", "secret", "bucket", Path("."), "Taiel")
                output = io.StringIO()
                with (
                    redirect_stdout(output),
                    patch("builtins.input", return_value="0"),
                    patch("bifrost.cli.read_world_state", return_value=self.make_snapshot(name)) as read,
                    patch("bifrost.cli.commit_world_state") as commit,
                ):
                    if menu is status_menu:
                        menu(storage)
                    else:
                        menu(settings, storage)
                read.assert_called_once_with(storage, name)
                commit.assert_not_called()
                client.download_fileobj.assert_not_called()
                client.put_object.assert_not_called()
                self.assertIn("Nombre de mundo inválido 'NUL'", output.getvalue())
                self.assertIn("Conflicto entre nombres de mundo 'Asgard', 'asgard'", output.getvalue())
                self.assertIn(name, output.getvalue())

    def test_remote_menus_with_only_rejected_names_do_not_offer_an_operation(self) -> None:
        for menu in (status_menu, pull_menu, copy_menu, lock_menu):
            with self.subTest(menu=menu.__name__):
                storage, client = self.make_storage(["Asgard", "asgard", "NUL"])
                settings = Settings("url", "id", "secret", "bucket", Path("."), "Taiel")
                output = io.StringIO()
                with (
                    redirect_stdout(output),
                    patch("builtins.input") as user_input,
                    patch("bifrost.cli.read_world_state") as read,
                    patch("bifrost.cli.commit_world_state") as commit,
                ):
                    if menu is status_menu:
                        menu(storage)
                    else:
                        menu(settings, storage)
                user_input.assert_not_called()
                read.assert_not_called()
                commit.assert_not_called()
                client.download_fileobj.assert_not_called()
                self.assertIn("[BLOQUEADO]", output.getvalue())

    def test_push_reports_rejected_local_names_and_keeps_the_valid_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            valid = root / "Peña del Dragón"
            valid.mkdir()
            (valid / "save.db").write_bytes(b"progress")
            entries = [valid]
            for name in ("Asgard", "asgard", "NUL"):
                entry = Mock(spec=Path)
                entry.name = name
                entry.is_dir.return_value = True
                entries.append(entry)
            settings = Settings("url", "id", "secret", "bucket", root, "Taiel")
            storage = Mock()
            output = io.StringIO()
            with (
                redirect_stdout(output),
                patch.object(Path, "iterdir", return_value=iter(entries)),
                patch("builtins.input", return_value="0"),
            ):
                push_menu(settings, storage)
            self.assertIn("Nombre de mundo inválido 'NUL'", output.getvalue())
            self.assertIn("Conflicto entre nombres de mundo 'Asgard', 'asgard'", output.getvalue())
            self.assertIn("1) Peña del Dragón", output.getvalue())
            self.assertEqual(storage.mock_calls, [])
            self.assertEqual((valid / "save.db").read_bytes(), b"progress")

    def test_pull_with_ambiguous_local_destination_does_not_acquire_a_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            entries = []
            for name in ("Asgard", "asgard"):
                entry = Mock(spec=Path)
                entry.name = name
                entry.is_dir.return_value = True
                entries.append(entry)
            settings = Settings("url", "id", "secret", "bucket", root, "Taiel")
            storage, client = self.make_storage(["Asgard"])
            output = io.StringIO()
            with (
                redirect_stdout(output),
                patch.object(Path, "iterdir", return_value=iter(entries)),
                patch("builtins.input", side_effect=["1", "s"]),
                patch("bifrost.cli.read_world_state", return_value=self.make_snapshot("Asgard")),
                patch("bifrost.cli.commit_world_state") as commit,
                patch("bifrost.cli.install_staged_world") as install,
            ):
                pull_menu(settings, storage)
            commit.assert_not_called()
            install.assert_not_called()
            client.download_fileobj.assert_not_called()
            self.assertIn("Conflicto entre nombres de mundo 'Asgard', 'asgard'", output.getvalue())


if __name__ == "__main__":
    unittest.main()
