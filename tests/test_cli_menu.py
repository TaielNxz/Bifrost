import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from bifrost.cli import run_menu
from bifrost.config import Settings


class MainMenuTests(unittest.TestCase):
    def test_option_four_downloads_copy_and_option_six_exits(self) -> None:
        settings = Settings("url", "id", "secret", "bucket", Path("."), "Taiel")
        storage = object()

        with (
            redirect_stdout(io.StringIO()) as output,
            patch("builtins.input", side_effect=["4", "6"]),
            patch("bifrost.cli.copy_menu") as copy_menu,
        ):
            run_menu(settings, storage)  # type: ignore[arg-type]

        copy_menu.assert_called_once_with(settings, storage)
        self.assertIn("3) Descargar para hostear", output.getvalue())
        self.assertIn("4) Descargar una copia", output.getvalue())
        self.assertIn("6) Salir", output.getvalue())


if __name__ == "__main__":
    unittest.main()
