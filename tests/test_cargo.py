"""Проверки HTTP-загрузки, формата индекса и прямых зависимостей Cargo."""

import io
import json
import sys
import unittest
from pathlib import Path
from http.client import IncompleteRead
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cargo import (
    MAX_INDEX_BYTES, TIMEOUT_SECONDS, Dependency, RepositoryError,
    fetch_index, format_dependency, index_path, load_package,
    parse_dependency, parse_records, select_release, stable_version_key,
)


def record(version="1.0.0", **changes):
    """Создать минимальную запись индекса с возможностью изменить поля."""
    return dict(
        {"name": "demo", "vers": version, "yanked": False, "deps": []},
        **changes,
    )


class IndexTests(unittest.TestCase):
    """Проверить правила каталогов, SemVer, JSON Lines и выбор релиза."""

    def test_index_paths(self):
        """Проверить все четыре схемы пути и приведение к нижнему регистру."""
        for name, expected in {
            "A": "1/a", "Ab": "2/ab", "ABC": "3/a/abc",
            "Serde": "se/rd/serde", "serde_json": "se/rd/serde_json",
        }.items():
            with self.subTest(name=name):
                self.assertEqual(index_path(name), expected)

    def test_invalid_names(self):
        """Имя пакета не может подменять путь HTTP-запроса."""
        for name in ("", "../demo", "demo?q=1", "a/b"):
            with self.subTest(name=name):
                with self.assertRaises(RepositoryError):
                    index_path(name)

    def test_semver(self):
        """Числовое сравнение версий и build metadata соответствуют SemVer."""
        self.assertGreater(stable_version_key("1.10.0"),
                           stable_version_key("1.9.99"))
        self.assertEqual(stable_version_key("2.0.1+build.7"), (2, 0, 1))
        self.assertIsNone(stable_version_key("3.0.0-rc.1+build"))
        self.assertIsNone(stable_version_key("0.1.0-alpha"))

    def test_invalid_versions(self):
        """Отклонять некорректные версии, включая ведущие нули."""
        for version in ("1.2", "v1.2.3", "01.2.3", "1.2.3-01", "oops"):
            with self.subTest(version=version):
                with self.assertRaises(RepositoryError):
                    stable_version_key(version)

    def test_choose_latest_stable(self):
        """Не полагаться на порядок строк; пропустить yanked и prerelease."""
        records = [
            record("1.9.0"), record("9.0.0", yanked=True),
            record("1.10.0", v=2), record("2.0.0-beta.1"), record("0.9.0"),
            record("3.0.0", v=99),
        ]
        self.assertEqual(select_release(records)["vers"], "1.10.0")

    def test_no_available_release(self):
        """Понятная ошибка при отсутствии подходящих стабильных версий."""
        for records in (
            [], [record(yanked=True)], [record("1.0.0-rc.1")],
            [record(v=99)],
        ):
            with self.subTest(records=records):
                with self.assertRaisesRegex(RepositoryError, "стабильной"):
                    select_release(records)

    def test_json_lines(self):
        """Прочитать несколько версий с пустой строкой и иным регистром."""
        text = "\n".join(json.dumps(record(v)) for v in ("1.0.0", "1.1.0"))
        result = parse_records(text + "\n\n", "DEMO")
        versions = [item["vers"] for item in result]
        self.assertEqual(versions, ["1.0.0", "1.1.0"])

    def test_bad_records(self):
        """Отклонять HTML, пустые данные, неверные поля и чужой пакет."""
        bad = [
            "", " \n", "<html>error</html>", "{", "[]", "null",
            json.dumps(record(name="other")),
            json.dumps(record(vers=None)),
            json.dumps(record(yanked="false")),
            json.dumps(record(v=True)),
        ]
        for text in bad:
            with self.subTest(text=text):
                with self.assertRaises(RepositoryError):
                    parse_records(text, "demo")


class DependencyTests(unittest.TestCase):
    """Проверить полноту списка зависимостей и ошибки метаданных."""

    def test_defaults(self):
        """Применять значения по умолчанию для kind и optional."""
        expected = Dependency("dep", "^1", "normal", False, None, None)
        for data in (
            {"name": "dep", "req": "^1"},
            {"name": "dep", "req": "^1", "kind": None},
        ):
            with self.subTest(data=data):
                self.assertEqual(parse_dependency(data), expected)

    def test_renamed_optional_target(self):
        """Сохранять настоящее имя, optional, target и внешний registry."""
        dep = parse_dependency({
            "name": "alias", "package": "real-package", "req": "~2.0",
            "kind": "build", "optional": True, "target": "cfg(windows)",
            "registry": "https://other.example/index",
        })
        self.assertEqual(dep.name, "real-package")
        self.assertEqual(format_dependency(dep),
                         "- real-package ~2.0 [build; optional; "
                         "target=cfg(windows); "
                         "registry=https://other.example/index]")

    def test_invalid_dependency(self):
        """Отклонять неправильные типы и неизвестные виды зависимостей."""
        base = {"name": "dep", "req": "^1"}
        changes = [
            {"name": ""}, {"name": "a/b"}, {"req": None}, {"req": "\nx"},
            {"optional": "true"}, {"kind": "unknown"}, {"target": []},
            {"registry": 1}, {"package": ""},
        ]
        for data in (None, [], *[dict(base, **item) for item in changes]):
            with self.subTest(data=data):
                with self.assertRaises(RepositoryError):
                    parse_dependency(data)

    @patch("cargo.fetch_index")
    def test_all_direct_dependencies(self, fetch):
        """Не терять dev, build, optional, target и повторяющиеся рёбра."""
        deps = [
            {"name": "ordinary", "req": "^1"},
            {"name": "development", "req": "*", "kind": "dev"},
            {"name": "builder", "req": "~2", "kind": "build"},
            {"name": "extra", "req": "^3", "optional": True},
            {"name": "ordinary", "req": "^2", "target": "cfg(unix)"},
        ]
        fetch.return_value = json.dumps(record(deps=deps))
        package = load_package("https://example.test/", "demo")
        self.assertEqual(package.version, "1.0.0")
        self.assertEqual(len(package.dependencies), len(deps))
        self.assertEqual(package.dependencies[1].kind, "dev")
        self.assertEqual(package.dependencies[2].kind, "build")
        self.assertTrue(package.dependencies[3].optional)
        self.assertEqual(package.dependencies[4].target, "cfg(unix)")
        fetch.assert_called_once_with("https://example.test/", "demo")

    @patch("cargo.fetch_index")
    def test_no_dependencies(self, fetch):
        """Пакет без зависимостей даёт пустой кортеж."""
        fetch.return_value = json.dumps(record())
        self.assertEqual(load_package("https://example.test/", "demo")
                         .dependencies, ())

    @patch("cargo.fetch_index")
    def test_missing_dependency_array(self, fetch):
        """Отсутствие массива deps не маскируется пустым списком."""
        for deps in (None, {}, "invalid"):
            with self.subTest(deps=deps):
                fetch.return_value = json.dumps(record(deps=deps))
                with self.assertRaisesRegex(RepositoryError, "deps"):
                    load_package("https://example.test/", "demo")


class HttpTests(unittest.TestCase):
    """Проверить сетевые ошибки и ограничения без реальных HTTP-запросов."""

    @patch("cargo.urlopen")
    def test_download(self, open_url):
        """Использовать URL пользователя, путь Cargo, таймаут и заголовок."""
        open_url.return_value = io.BytesIO(b'{"name":"demo"}\n')
        text = fetch_index("https://example.test/custom/", "Demo")
        self.assertEqual(text, '{"name":"demo"}\n')
        args, kwargs = open_url.call_args
        self.assertEqual(args[0].full_url,
                         "https://example.test/custom/de/mo/demo")
        self.assertEqual(kwargs["timeout"], TIMEOUT_SECONDS)
        self.assertIn("dependency-graph", args[0].get_header("User-agent"))

    @patch("cargo.urlopen")
    def test_http_errors(self, open_url):
        """Различать отсутствие пакета и другие HTTP-ошибки."""
        for code in (404, 403, 429, 500):
            with self.subTest(code=code):
                open_url.side_effect = HTTPError(
                    "https://example.test/", code, "failure", None, None,
                )
                with self.assertRaisesRegex(RepositoryError, str(code)):
                    fetch_index("https://example.test/", "demo")

    @patch("cargo.urlopen")
    def test_network_errors(self, open_url):
        """Обрабатывать DNS, TLS, соединение и таймаут единым сообщением."""
        for error in (URLError("DNS/TLS failure"), TimeoutError("timed out"),
                      ConnectionError("connection reset"),
                      IncompleteRead(b"partial", 100)):
            with self.subTest(error=error):
                open_url.side_effect = error
                with self.assertRaisesRegex(RepositoryError, "загрузить"):
                    fetch_index("https://example.test/", "demo")

    @patch("cargo.urlopen")
    def test_response_read_error(self, open_url):
        """Сетевой сбой при чтении тела тоже должен обрабатываться."""
        open_url.return_value.__enter__.return_value.read.side_effect = (
            TimeoutError("timed out while reading")
        )
        with self.assertRaises(RepositoryError):
            fetch_index("https://example.test/", "demo")

    @patch("cargo.urlopen")
    def test_invalid_encoding(self, open_url):
        """Отвергать ответ, который нельзя декодировать как UTF-8."""
        open_url.return_value = io.BytesIO(b"\xff")
        with self.assertRaisesRegex(RepositoryError, "UTF-8"):
            fetch_index("https://example.test/", "demo")

    @patch("cargo.urlopen")
    def test_size_limit(self, open_url):
        """Ограничивать размер ответа перед разбором JSON."""
        stream = open_url.return_value.__enter__.return_value
        stream.read.return_value = b"x" * (MAX_INDEX_BYTES + 1)
        with self.assertRaisesRegex(RepositoryError, "размер"):
            fetch_index("https://example.test/", "demo")
        stream.read.assert_called_once_with(MAX_INDEX_BYTES + 1)


if __name__ == "__main__":
    unittest.main()
