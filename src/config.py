"""Чтение и проверка CSV-конфигурации приложения."""

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

FIELDS = (
    "package_name", "repository", "test_mode", "output_file",
    "ascii_tree", "filter_substring",
)
ROW_SIZE = 2
MIN_PORT = 1
PACKAGE_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_-]*"


class ConfigError(ValueError):
    """Ошибка чтения или проверки пользовательской конфигурации."""


@dataclass(frozen=True)
class Config:
    """Шесть проверенных параметров из CSV; пути хранятся как в файле."""

    package_name: str
    repository: str
    test_mode: bool
    output_file: str
    ascii_tree: bool
    filter_substring: str


def read_values(path: Path) -> dict[str, str]:
    """Прочитать CSV с заголовком key,value и проверить набор ключей."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = csv.reader(stream, strict=True)
            if next(rows, None) != ["key", "value"]:
                raise ConfigError("Ожидается заголовок CSV: key,value")
            values = collect_rows(rows)
    except (OSError, UnicodeError, csv.Error) as error:
        raise ConfigError(f"Не удалось прочитать CSV: {error}") from error
    missing = set(FIELDS) - values.keys()
    if missing:
        message = "Отсутствуют параметры: " + ", ".join(sorted(missing))
        raise ConfigError(message)
    return values


def collect_rows(rows) -> dict[str, str]:
    """Проверить строки, неизвестные ключи, повторы и управляющие символы."""
    values = {}
    for number, row in enumerate(rows, start=ROW_SIZE):
        if len(row) != ROW_SIZE:
            raise ConfigError(f"Строка {number}: нужны два столбца")
        key, value = row
        if key not in FIELDS:
            raise ConfigError(f"Строка {number}: неизвестный параметр {key!r}")
        if key in values:
            raise ConfigError(f"Параметр {key} указан повторно")
        if not value.isprintable() and value:
            raise ConfigError(f"{key}: управляющие символы запрещены")
        values[key] = value
    return values


def parse_bool(name: str, value: str) -> bool:
    """Принимать только явные значения true и false."""
    if value not in ("true", "false"):
        raise ConfigError(f"{name}: ожидается true или false")
    return value == "true"


def resolve_path(value: str, base: Path) -> Path:
    """Разрешить относительный путь относительно CSV-конфигурации."""
    path = Path(value)
    return path if path.is_absolute() else base / path


def validate_repository(value: str, test_mode: bool, base: Path) -> None:
    """Проверить локальный файл либо синтаксис HTTP(S)-адреса без сети."""
    if not value or value != value.strip():
        raise ConfigError(
            "repository: нужен непустой URL или путь без пробелов по краям"
        )
    if test_mode:
        path = resolve_path(value, base)
        try:
            with path.open("rb"):
                pass
        except OSError as error:
            message = f"repository: файл недоступен: {error}"
            raise ConfigError(message) from error
        return
    try:
        url = urlsplit(value)
        valid = url.scheme in ("http", "https") and url.hostname
        valid = valid and not any(char.isspace() for char in value)
        valid = valid and not url.username and not url.password
        port = url.port
        valid = valid and (port is None or port >= MIN_PORT)
    except ValueError as error:
        raise ConfigError(f"repository: некорректный URL: {error}") from error
    if not valid:
        raise ConfigError("repository: ожидается HTTP(S)-URL с именем хоста")


def validate_output(value: str, base: Path) -> None:
    """Проверить имя SVG и существование папки, не создавая изображение."""
    if not value or value != value.strip():
        raise ConfigError("output_file: укажите непустое имя SVG-файла")
    path = resolve_path(value, base)
    if path.suffix.lower() != ".svg":
        raise ConfigError("output_file: требуется расширение .svg")
    if not path.parent.is_dir() or path.is_dir():
        raise ConfigError("output_file: неверный путь или папка не существует")
    if path.exists() and not path.is_file():
        raise ConfigError("output_file: путь должен вести к обычному файлу")


def load_config(path: Path) -> Config:
    """Прочитать конфигурацию и проверить все шесть параметров."""
    values = read_values(path)
    if not re.fullmatch(PACKAGE_PATTERN, values["package_name"]):
        raise ConfigError(
            "package_name: нужны латинские буквы, цифры, '-' или '_'; "
            "первый символ — буква или цифра"
        )
    test_mode = parse_bool("test_mode", values["test_mode"])
    ascii_tree = parse_bool("ascii_tree", values["ascii_tree"])
    validate_repository(values["repository"], test_mode, path.resolve().parent)
    validate_output(values["output_file"], path.resolve().parent)
    return Config(
        package_name=values["package_name"],
        repository=values["repository"],
        test_mode=test_mode,
        output_file=values["output_file"],
        ascii_tree=ascii_tree,
        filter_substring=values["filter_substring"],
    )
