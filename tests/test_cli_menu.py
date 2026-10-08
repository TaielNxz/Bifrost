import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from bifrost.cli import run_menu
from bifrost.config import Settings


class MainMenuTests(unittest.TestCase):
    def test_option_four_downloads_copy_and_option_seven_exits(self) -> None:
        settings = Settings("url", "id", "secret", "bucket", Path("."), "Taiel")
        storage = object()

        with (
            redirect_stdout(io.StringIO()) as output,
            patch("builtins.input", side_effect=["4", "7"]),
            patch("bifrost.cli.copy_menu") as copy_menu,
        ):
            run_menu(settings, storage)  # type: ignore[arg-type]

        copy_menu.assert_called_once_with(settings, storage)
        self.assertIn("3) Descargar para hostear", output.getvalue())
        self.assertIn("4) Descargar una copia", output.getvalue())
        self.assertIn("7) Salir", output.getvalue())

    def test_option_six_restores_and_returns_to_main_menu(self) -> None:
        settings = Settings("url", "id", "secret", "bucket", Path("."), "Taiel")
        storage = object()
        with (
            redirect_stdout(io.StringIO()) as output,
            patch("builtins.input", side_effect=["6", "7"]),
            patch("bifrost.cli.restore_menu") as restore_menu,
        ):
            run_menu(settings, storage)  # type: ignore[arg-type]
        restore_menu.assert_called_once_with(settings, storage)
        self.assertIn("6) Restaurar una versión anterior", output.getvalue())
        self.assertEqual(output.getvalue().count("=== Bifröst ==="), 2)
        self.assertIn("¡Chau!", output.getvalue())


if __name__ == "__main__":
    unittest.main()
