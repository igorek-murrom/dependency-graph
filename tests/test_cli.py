"""Проверки CLI третьего этапа на тестовом и сетевом источниках."""

import io
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cargo import Dependency, Package, RepositoryError
from config import Config
from main import analyze, main

ROOT = Path(__file__).resolve().parents[1]
CONFIG_ERROR_EXIT_CODE = 2
REPOSITORY_ERROR_EXIT_CODE = 3


class CliTests(unittest.TestCase):
    """Проверить готовые демонстрации и отсутствие частичного вывода ошибок."""

    def run_cli(self, *args):
        """Запустить приложение из другой папки и сохранить оба потока."""
        return subprocess.run(
            [sys.executable, str(ROOT / "src/main.py"), *map(str, args)],
            cwd=ROOT.parent, capture_output=True, text=True, check=False,
        )

    def run_main(self, path):
        """Выполнить точку входа с захватом результата и сообщений."""
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main([str(path)])
        return code, output.getvalue(), errors.getvalue()

    def test_test_mode(self):
        """Реальный запуск CLI должен пройти всю цепочку из JSON без сети."""
        result = self.run_cli(ROOT / "examples/test-config.csv")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout.splitlines(), [
            "Граф зависимостей (DFS):", "A -> B", "B -> C",
            "C -> нет зависимостей",
        ])

    def test_diamond(self):
        """Вывод должен показать общую вершину и порядок DFS."""
        result = self.run_cli(ROOT / "examples/diamond-config.csv")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "Граф зависимостей (DFS):", "A -> B, C", "B -> D",
            "D -> нет зависимостей", "C -> D",
        ])

    def test_cycle(self):
        """Цикл и петля сохраняются в выводе; процесс завершается."""
        result = self.run_cli(ROOT / "examples/cycle-config.csv")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "Граф зависимостей (DFS):", "A -> B", "B -> C, B", "C -> A",
        ])

    def test_filter(self):
        """Удалить B, сохранив D, достижимую через C."""
        result = self.run_cli(ROOT / "examples/filter-config.csv")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "Граф зависимостей (DFS):", "A -> C", "C -> D",
            "D -> нет зависимостей",
        ])

    def test_filter_root(self):
        """Исключение самого корня даёт понятный успешный результат."""
        result = self.run_cli(ROOT / "examples/root-filter-config.csv")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Граф пуст", result.stdout)

    def test_leaf(self):
        """Показать пакет без зависимостей."""
        result = self.run_cli(ROOT / "examples/leaf-config.csv")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("C -> нет зависимостей", result.stdout)

    @patch("repository.load_package")
    def test_cargo_graph(self, load):
        """Обойти транзитивные зависимости Cargo и сохранить цикл."""
        load.side_effect = [
            Package("serde", "1.0.229", (
                Dependency("dep", "^1", "normal", False, None, None),
            )),
            Package("dep", "1.0.0", (
                Dependency("serde", "^1", "dev", False, None, None),
            )),
        ]
        code, output, errors = self.run_main(ROOT / "examples/config.csv")
        self.assertEqual(code, 0)
        self.assertEqual(errors, "")
        self.assertEqual(output.splitlines(), [
            "Граф зависимостей (DFS):", "serde -> dep", "dep -> serde",
        ])
        self.assertEqual([args.args[1] for args in load.call_args_list],
                         ["serde", "dep"])

    @patch("repository.load_package")
    def test_repository_error(self, load):
        """Ошибка после загрузки корня не оставляет частичного графа."""
        load.side_effect = [
            Package("serde", "1.0.229", (
                Dependency("missing", "^1", "normal", False, None, None),
            )),
            RepositoryError("HTTP 404"),
        ]
        code, output, errors = self.run_main(ROOT / "examples/config.csv")
        self.assertEqual(code, REPOSITORY_ERROR_EXIT_CODE)
        self.assertEqual(output, "")
        self.assertIn("Ошибка репозитория: HTTP 404", errors)
        self.assertNotIn("Traceback", errors)

    @patch("repository.load_package")
    def test_remote_filtered_root(self, load):
        """Совпавший с фильтром Cargo-корень не загружается."""
        config = Config("Serde", "https://index.crates.io/", False,
                        "graph.svg", False, "serde")
        self.assertEqual(analyze(config, ROOT / "examples/config.csv"), {})
        load.assert_not_called()

    def test_config_error(self):
        """Ошибки аргументов и настроек сохраняют код 2."""
        result = self.run_cli(ROOT / "missing.csv")
        self.assertEqual(result.returncode, CONFIG_ERROR_EXIT_CODE)
        self.assertEqual(result.stdout, "")
        self.assertIn("Ошибка конфигурации:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_json_is_not_config(self):
        """JSON-репозиторий нельзя передавать вместо CSV-конфигурации."""
        result = self.run_cli(ROOT / "examples/repository.json")
        self.assertEqual(result.returncode, CONFIG_ERROR_EXIT_CODE)
        self.assertIn("key,value", result.stderr)

    def test_help(self):
        """Показать справку о CSV и алгоритме этапа 3."""
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("CSV", result.stdout)
        self.assertIn("DFS", result.stdout)

    def test_missing_argument(self):
        """Без пути к CSV сообщить об ошибке запуска."""
        result = self.run_cli()
        self.assertEqual(result.returncode, CONFIG_ERROR_EXIT_CODE)


if __name__ == "__main__":
    unittest.main()
