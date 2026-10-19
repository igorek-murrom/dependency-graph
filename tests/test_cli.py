"""Проверки интерфейса приложения через отдельный процесс."""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERROR_EXIT_CODE = 2


class CliTests(unittest.TestCase):
    """Проверить пользовательский вывод, справку и коды завершения."""

    def run_cli(self, *args):
        """Запустить приложение вне папки проекта, сохранив оба потока."""
        return subprocess.run(
            [sys.executable, str(ROOT / "src/main.py"), *map(str, args)],
            cwd=ROOT.parent, capture_output=True, text=True, check=False,
        )

    def test_success(self):
        """Вывести ровно шесть строк ключ=значение в заданном порядке."""
        result = self.run_cli(ROOT / "examples/config.csv")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout.splitlines(), [
            "package_name=serde",
            "repository=https://index.crates.io/",
            "test_mode=false", "output_file=graph.svg",
            "ascii_tree=false", "filter_substring=",
        ])

    def test_test_mode(self):
        """Локальный пример работает из другой рабочей папки."""
        result = self.run_cli(ROOT / "examples/test-config.csv")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("test_mode=true\n", result.stdout)

    def test_config_error(self):
        """Сообщить об ошибке без traceback и без частичного вывода."""
        result = self.run_cli(ROOT / "missing.csv")
        self.assertEqual(result.returncode, ERROR_EXIT_CODE)
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
        self.assertEqual(result.returncode, ERROR_EXIT_CODE)


if __name__ == "__main__":
    unittest.main()
