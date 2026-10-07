import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from bifrost.cli import status_menu
from bifrost.world_names import filter_world_names


class FakeStatusStorage:
    def __init__(self, worlds=None, manifests=None, locks=None) -> None:
        self.worlds = worlds or []
        self.manifests = manifests or {}
        self.locks = locks or {}

    def list_worlds(self, *, errors=None):
        return filter_world_names(self.worlds, errors=errors)

    def read_manifest(self, world_name):
        return self.manifests.get(world_name)

    def read_lock(self, world_name):
        return self.locks.get(world_name)


class InvalidJsonStorage(FakeStatusStorage):
    def read_manifest(self, world_name):
        raise ValueError("JSON inválido")


def render_status(storage: FakeStatusStorage) -> str:
    output = io.StringIO()
    with redirect_stdout(output):
        status_menu(storage)  # type: ignore[arg-type]
    return output.getvalue()


class StatusMenuTests(unittest.TestCase):
    def test_empty_remote_list(self) -> None:
        output = render_status(FakeStatusStorage())
        self.assertIn("No hay mundos disponibles en la nube.", output)

    def test_free_world_displays_manifest(self) -> None:
        storage = FakeStatusStorage(
            worlds=["Asgard"],
            manifests={
                "Asgard": {
                    "version": 12,
                    "uploaded_at": "2026-09-30T22:15:00Z",
                    "uploaded_by": "Taiel",
                    "size": 88_709_530,
                }
            },
        )
        output = render_status(storage)
        self.assertIn("Asgard", output)
        self.assertIn("Versión:        12", output)
        self.assertIn("Última subida:  2026-09-30 22:15 UTC", output)
        self.assertIn("Subido por:     Taiel", output)
        self.assertIn("Tamaño:         84.6 MB", output)
        self.assertIn("Estado:         Libre", output)

    def test_active_lock_displays_owner_machine_and_expiration(self) -> None:
        storage = FakeStatusStorage(
            worlds=["Asgard"],
            manifests={"Asgard": None},
            locks={
                "Asgard": {
                    "player": "Lucas",
                    "machine": "PC-LUCAS",
                    "acquired_at": "2099-01-01T00:00:00Z",
                    "expires_at": "2099-01-01T12:00:00Z",
                }
            },
        )
        output = render_status(storage)
        self.assertIn("Manifest:       No disponible", output)
        self.assertIn("Estado:         En uso por Lucas (PC-LUCAS)", output)
        self.assertIn("Lock vence:     2099-01-01 12:00 UTC", output)

    def test_expired_lock_is_displayed_as_free(self) -> None:
        storage = FakeStatusStorage(
            worlds=["Asgard"],
            locks={
                "Asgard": {
                    "player": "Lucas",
                    "machine": "PC-LUCAS",
                    "acquired_at": "2000-01-01T00:00:00Z",
                    "expires_at": "2000-01-01T12:00:00Z",
                }
            },
        )
        self.assertIn("Estado:         Libre", render_status(storage))

    def test_invalid_manifest_does_not_hide_other_worlds(self) -> None:
        storage = FakeStatusStorage(
            worlds=["Asgard", "Mundazo"],
            manifests={"Asgard": {"version": 1}, "Mundazo": None},
        )
        output = render_status(storage)
        self.assertIn("Manifest:       Inválido", output)
        self.assertIn("Mundazo", output)

    def test_invalid_manifest_json_is_reported(self) -> None:
        storage = InvalidJsonStorage(worlds=["Asgard"])
        self.assertIn("Manifest:       Inválido", render_status(storage))

    def test_rejected_names_are_reported_without_reading_their_metadata(self) -> None:
        storage = FakeStatusStorage(worlds=["NUL", "Asgard", "asgard", "Peña del Dragón"])
        with patch.object(storage, "read_manifest", return_value=None) as reader:
            output = render_status(storage)
        reader.assert_called_once_with("Peña del Dragón")
        self.assertIn("[BLOQUEADO] Nombre de mundo inválido 'NUL'", output)
        self.assertIn("Conflicto entre nombres de mundo 'Asgard', 'asgard'", output)
        self.assertIn("Peña del Dragón", output)
        self.assertIn("Estado:         Libre", output)


if __name__ == "__main__":
    unittest.main()
