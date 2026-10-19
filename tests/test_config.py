"""Проверки успешных конфигураций и ошибок каждого параметра."""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    """Проверять CSV в изолированной временной папке без доступа к сети."""

    def setUp(self):
        """Подготовить допустимую конфигурацию и тестовый репозиторий."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "config.csv"
        (self.root / "repo.json").write_text("{}", encoding="utf-8")
        self.values = {
            "package_name": "serde",
            "repository": "https://index.crates.io/",
            "test_mode": "false",
            "output_file": "graph.svg",
            "ascii_tree": "false",
            "filter_substring": "",
        }

    def write_config(self):
        """Сохранить текущие значения корректным CSV-писателем."""
        with self.path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["key", "value"])
            writer.writerows(self.values.items())

    def test_valid_remote(self):
        """Проверить все значения конфигурации обычного режима."""
        self.write_config()
        config = load_config(self.path)
        for name, value in self.values.items():
            expected = False if value == "false" else value
            self.assertEqual(getattr(config, name), expected)

    def test_valid_local(self):
        """Проверить локальный путь относительно CSV и оба флага true."""
        self.values.update(
            package_name="A", repository="repo.json", test_mode="true",
            ascii_tree="true", filter_substring="B",
        )
        self.write_config()
        config = load_config(self.path)
        self.assertTrue(config.test_mode)
        self.assertTrue(config.ascii_tree)
        self.assertEqual(config.repository, "repo.json")
        self.assertEqual(config.filter_substring, "B")

    def test_invalid_parameters(self):
        """Продемонстрировать отказ для каждого из шести параметров."""
        cases = {
            "package_name": ["", "bad/name", "имя", "-serde", "a b"],
            "repository": [
                "", "repo.json", "ftp://host", "https://",
                "https://a b", "https://host:bad", "https://host:0",
                "https://[broken", "https://user:pass@host",
            ],
            "test_mode": ["", "yes", "1", "False"],
            "output_file": ["", "graph.png", "missing/graph.svg", ".svg"],
            "ascii_tree": ["", "no", "0", "TRUE"],
            "filter_substring": ["line\nbreak", "tab\there", "\x00"],
        }
        original = self.values.copy()
        for field, invalid_values in cases.items():
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    self.values = dict(original, **{field: value})
                    self.write_config()
                    with self.assertRaisesRegex(ConfigError, field):
                        load_config(self.path)

    def test_missing_every_parameter(self):
        """Любой из шести ключей обязателен, включая пустой фильтр."""
        original = self.values.copy()
        for field in original:
            with self.subTest(field=field):
                self.values = original.copy()
                del self.values[field]
                self.write_config()
                with self.assertRaisesRegex(ConfigError, field):
                    load_config(self.path)

    def test_invalid_local_repository(self):
        """Отклонять отсутствующий файл и каталог вместо репозитория."""
        self.values["test_mode"] = "true"
        for value in ("missing.json", "."):
            with self.subTest(value=value):
                self.values["repository"] = value
                self.write_config()
                with self.assertRaisesRegex(ConfigError, "repository"):
                    load_config(self.path)

    def test_output_directory(self):
        """Имя каталога с расширением SVG не является выходным файлом."""
        (self.root / "dir.svg").mkdir()
        self.values["output_file"] = "dir.svg"
        self.write_config()
        with self.assertRaisesRegex(ConfigError, "output_file"):
            load_config(self.path)

    def test_quoted_filter_and_bom(self):
        """Поддерживать запятую внутри значения и UTF-8 BOM."""
        self.values["filter_substring"] = "a,b"
        self.write_config()
        content = self.path.read_text(encoding="utf-8")
        self.path.write_text(content, encoding="utf-8-sig")
        self.assertEqual(load_config(self.path).filter_substring, "a,b")

    def test_bad_csv_structure(self):
        """Отклонять заголовок, повторы, лишние ключи и поврежденный CSV."""
        cases = (
            "", "name,value\n", "key,value\npackage_name\n",
            "key,value\npackage_name,a,extra\n",
            "key,value\nunknown,value\n",
            "key,value\npackage_name,a\npackage_name,b\n",
            'key,value\npackage_name,"unterminated',
        )
        for content in cases:
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                with self.assertRaises(ConfigError):
                    load_config(self.path)

    def test_unreadable_config(self):
        """Отклонять отсутствующий CSV, каталог и неверную кодировку."""
        for path in (self.path, self.root):
            with self.subTest(path=path):
                with self.assertRaises(ConfigError):
                    load_config(path)
        self.path.write_bytes(b"\xff\xfe")
        with self.assertRaises(ConfigError):
            load_config(self.path)


if __name__ == "__main__":
    unittest.main()
