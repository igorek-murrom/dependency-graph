"""Проверки тестового JSON-репозитория и источника Cargo."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cargo import Dependency, Package, RepositoryError
from config import Config
from repository import (
    CRATES_GIT_INDEX, cargo_dependencies, create_loader,
    load_test_repository, normalize_registry, test_dependencies,
)


class TestRepositoryTests(unittest.TestCase):
    """Проверить чтение JSON и ошибки описания тестового графа."""

    def setUp(self):
        """Создать отдельную временную папку для каждого случая."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "repository.json"

    def write_graph(self, graph):
        """Сохранить граф как UTF-8 JSON."""
        self.path.write_text(json.dumps(graph), encoding="utf-8")

    def test_read_graph(self):
        """Прочитать цепочку и удалить повторные рёбра."""
        self.write_graph({"A": ["B", "B"], "B": ["C"], "C": []})
        self.assertEqual(load_test_repository(self.path),
                         {"A": ("B",), "B": ("C",), "C": ()})

    def test_cycle_is_valid(self):
        """Цикл и петля допустимы в описании репозитория."""
        self.write_graph({"A": ["B", "A"], "B": ["A"]})
        self.assertEqual(load_test_repository(self.path),
                         {"A": ("B", "A"), "B": ("A",)})

    def test_bom_and_long_name(self):
        """Поддержать UTF-8 BOM и имена из нескольких заглавных букв."""
        self.path.write_text('{"ABC": []}', encoding="utf-8-sig")
        self.assertEqual(load_test_repository(self.path), {"ABC": ()})

    def test_invalid_structure(self):
        """Отклонять неверные контейнеры и имена пакетов."""
        cases = (
            [], None, "text", {"A": "B"}, {"A": None},
            {"a": []}, {"А": []}, {"A1": []}, {"": []},
            {"A": [1]}, {"A": [None]}, {"A": ["b"]}, {"A": [{}]},
        )
        for data in cases:
            with self.subTest(data=data):
                self.write_graph(data)
                with self.assertRaises(RepositoryError):
                    load_test_repository(self.path)

    def test_missing_reference(self):
        """Каждый упомянутый пакет должен иметь своё описание."""
        self.write_graph({"A": ["B"]})
        with self.assertRaisesRegex(RepositoryError, "B"):
            load_test_repository(self.path)

    def test_duplicate_key(self):
        """Не допускать молчаливую перезапись повторного JSON-ключа."""
        self.path.write_text('{"A": ["A"], "A": []}', encoding="utf-8")
        with self.assertRaisesRegex(RepositoryError, "Повторное имя"):
            load_test_repository(self.path)

    def test_invalid_file(self):
        """Обработать отсутствие файла, каталог, кодировку и JSON-синтаксис."""
        for path in (self.path, self.root):
            with self.subTest(path=path):
                with self.assertRaises(RepositoryError):
                    load_test_repository(path)
        self.path.write_bytes(b"\xff")
        with self.assertRaises(RepositoryError):
            load_test_repository(self.path)
        self.path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(RepositoryError):
            load_test_repository(self.path)

    def test_empty_and_missing_root(self):
        """Различать пустой файл описания графа и отсутствие нужного пакета."""
        self.write_graph({})
        self.assertEqual(load_test_repository(self.path), {})
        with self.assertRaisesRegex(RepositoryError, "не найден"):
            test_dependencies({}, "A")
        with self.assertRaises(RepositoryError):
            test_dependencies({"A": ()}, "a")

    def test_local_loader(self):
        """Разрешать путь JSON относительно CSV независимо от рабочей папки."""
        self.write_graph({"A": ["B"], "B": []})
        config = Config("A", "repository.json", True, "graph.svg", False, "")
        with patch("repository.load_package") as load:
            loader = create_loader(config, self.root)
            self.assertEqual(loader("A"), ("B",))
            self.assertEqual(loader("B"), ())
            load.assert_not_called()


class CargoRepositoryTests(unittest.TestCase):
    """Проверить переход от записей индекса Cargo к именам вершин графа."""

    @patch("repository.load_package")
    def test_names_and_renamed_dependency(self, load):
        """Использовать настоящее имя из Package и привести регистр."""
        load.return_value = Package("demo", "1.0.0", (
            Dependency("Real_Crate", "^1", "normal", False, None, None),
            Dependency("dev", "^1", "dev", False, None, None),
        ))
        self.assertEqual(cargo_dependencies("https://index.crates.io/", "demo"),
                         ("real_crate", "dev"))
        load.assert_called_once_with("https://index.crates.io/", "demo")

    def test_registry_aliases(self):
        """Сопоставлять Git и sparse-адреса одного реестра crates.io."""
        for url in (CRATES_GIT_INDEX, "sparse+https://index.crates.io/"):
            with self.subTest(url=url):
                self.assertEqual(normalize_registry(url),
                                 "https://index.crates.io")

    @patch("repository.load_package")
    def test_explicit_same_registry(self, load):
        """Разрешить явное указание того же реестра в записи зависимости."""
        load.return_value = Package("demo", "1.0.0", (
            Dependency("dep", "^1", "build", False, None, CRATES_GIT_INDEX),
        ))
        self.assertEqual(cargo_dependencies("https://index.crates.io/", "demo"),
                         ("dep",))

    @patch("repository.load_package")
    def test_other_registry(self, load):
        """Не получать пакет из неверного реестра при внешней зависимости."""
        load.return_value = Package("demo", "1.0.0", (
            Dependency("dep", "^1", "normal", False, None,
                       "https://other.example/"),
        ))
        with self.assertRaisesRegex(RepositoryError, "другом реестре"):
            cargo_dependencies("https://index.crates.io/", "demo")

    @patch("repository.load_package")
    def test_filtered_external_dependency(self, load):
        """Исключённая внешняя зависимость не должна мешать обходу."""
        load.return_value = Package("demo", "1.0.0", (
            Dependency("external", "^1", "normal", False, None,
                       "https://other.example/"),
        ))
        self.assertEqual(cargo_dependencies(
            "https://index.crates.io/", "demo", "external",
        ), ())

    @patch("repository.cargo_dependencies")
    def test_remote_loader(self, load):
        """Передавать URL пользователя и имя в источник Cargo."""
        load.return_value = ("dep",)
        config = Config("demo", "https://example.test/index/", False,
                        "graph.svg", False, "")
        loader = create_loader(config, Path("."))
        self.assertEqual(loader("demo"), ("dep",))
        load.assert_called_once_with(config.repository, "demo", substring="")


if __name__ == "__main__":
    unittest.main()
