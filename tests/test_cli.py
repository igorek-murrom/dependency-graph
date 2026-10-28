"""Проверки вывода прямых зависимостей и ошибок пользовательского интерфейса."""

import io
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cargo import Dependency, Package, RepositoryError
from main import main

ROOT = Path(__file__).resolve().parents[1]

CONFIG_ERROR_EXIT_CODE = 2
REPOSITORY_ERROR_EXIT_CODE = 3


class CliTests(unittest.TestCase):
    """Проверить CLI без обращения к внешнему репозиторию."""

    def run_cli(self, *args):
        """Запустить приложение вне папки проекта, сохранив оба потока."""
        return subprocess.run(
            [sys.executable, str(ROOT / "src/main.py"), *map(str, args)],
            cwd=ROOT.parent, capture_output=True, text=True, check=False,
        )

    def run_main(self, path):
        """Запустить точку входа с захватом stdout и stderr."""
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main([str(path)])
        return code, output.getvalue(), errors.getvalue()

    @patch("main.load_package")
    def test_success(self, load):
        """Вывести версию и прямые зависимости вместо настроек этапа 1."""
        load.return_value = Package("serde", "1.0.228", (
            Dependency("serde_core", "=1.0.228", "normal", False, None, None),
            Dependency("serde_derive", "^1", "normal", True, None, None),
        ))
        code, output, errors = self.run_main(ROOT / "examples/config.csv")
        self.assertEqual(code, 0)
        self.assertEqual(errors, "")
        self.assertEqual(output.splitlines(), [
            "Пакет: serde 1.0.228", "Прямые зависимости:",
            "- serde_core =1.0.228 [normal]",
            "- serde_derive ^1 [normal; optional]",
        ])
        load.assert_called_once_with("https://index.crates.io/", "serde")

    @patch("main.load_package")
    def test_empty_dependencies(self, load):
        """Отдельно сообщить, что у выбранной версии нет зависимостей."""
        load.return_value = Package("serde", "1.0.0", ())
        code, output, errors = self.run_main(ROOT / "examples/config.csv")
        self.assertEqual(code, 0)
        self.assertIn("Прямых зависимостей нет.", output)
        self.assertEqual(errors, "")

    @patch("main.load_package")
    def test_repository_error(self, load):
        """Сетевая ошибка не должна оставлять частичный результат в stdout."""
        load.side_effect = RepositoryError("HTTP 404")
        code, output, errors = self.run_main(ROOT / "examples/config.csv")
        self.assertEqual(code, REPOSITORY_ERROR_EXIT_CODE)
        self.assertEqual(output, "")
        self.assertIn("Ошибка репозитория: HTTP 404", errors)
        self.assertNotIn("Traceback", errors)

    @patch("main.load_package")
    def test_test_mode(self, load):
        """До этапа 3 тестовый режим явно недоступен и не обращается к сети."""
        code, output, errors = self.run_main(ROOT / "examples/test-config.csv")
        self.assertEqual(code, REPOSITORY_ERROR_EXIT_CODE)
        self.assertEqual(output, "")
        self.assertIn("этапе 3", errors)
        load.assert_not_called()

    def test_config_error(self):
        """Сообщить об ошибке без traceback и без частичного вывода."""
        result = self.run_cli(ROOT / "missing.csv")
        self.assertEqual(result.returncode, CONFIG_ERROR_EXIT_CODE)
        self.assertEqual(result.stdout, "")
        self.assertIn("Ошибка конфигурации:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_help(self):
        """Справка завершается успешно и объясняет аргумент config."""
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("CSV", result.stdout)

    def test_missing_argument(self):
        """Без пути к CSV программа сообщает об ошибке запуска."""
        result = self.run_cli()
        self.assertEqual(result.returncode, CONFIG_ERROR_EXIT_CODE)


if __name__ == "__main__":
    unittest.main()
