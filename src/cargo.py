"""Получение прямых зависимостей из HTTP-индекса Cargo без менеджера пакетов."""

import json
import re
from dataclasses import dataclass
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import PACKAGE_PATTERN

TIMEOUT_SECONDS = 15
MAX_INDEX_BYTES = 20 * 1024 * 1024
HTTP_NOT_FOUND = 404
SHORT_NAME_LENGTH = 2
THREE_LETTER_LENGTH = 3
PREFIX_LENGTH = 2
SHARD_LENGTH = 4
SUPPORTED_SCHEMAS = (1, 2)
VERSION_NUMBER = r"(?:0|[1-9][0-9]*)"
PRERELEASE_ID = r"(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
VERSION_PATTERN = re.compile(
    rf"({VERSION_NUMBER})\.({VERSION_NUMBER})\.({VERSION_NUMBER})"
    rf"(?:-({PRERELEASE_ID}(?:\.{PRERELEASE_ID})*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
VERSION_COMPONENTS = (1, 2, 3)
PRERELEASE_GROUP = 4


class RepositoryError(ValueError):
    """Ошибка загрузки или структуры данных репозитория Cargo."""


@dataclass(frozen=True)
class Dependency:
    """Прямая объявленная зависимость, включая тип и ограничения платформы."""

    name: str
    requirement: str
    kind: str
    optional: bool
    target: str | None
    registry: str | None


@dataclass(frozen=True)
class Package:
    """Выбранная версия пакета и все объявленные прямые зависимости."""

    name: str
    version: str
    dependencies: tuple[Dependency, ...]


def index_path(package_name: str) -> str:
    """Построить путь к пакету по официальной схеме каталогов Cargo."""
    if not re.fullmatch(PACKAGE_PATTERN, package_name):
        raise RepositoryError("Недопустимое имя пакета")
    name = package_name.lower()
    length = len(name)
    if length <= SHORT_NAME_LENGTH:
        return f"{length}/{name}"
    if length == THREE_LETTER_LENGTH:
        return f"3/{name[0]}/{name}"
    return f"{name[:PREFIX_LENGTH]}/{name[PREFIX_LENGTH:SHARD_LENGTH]}/{name}"


def fetch_index(repository: str, package_name: str) -> str:
    """Загрузить один файл индекса по HTTP(S) с лимитом размера и таймаутом."""
    url = repository.rstrip("/") + "/" + index_path(package_name)
    request = Request(url, headers={
        "User-Agent": "dependency-graph/0.2 (educational project)",
        "Accept": "text/plain",
    })
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = response.read(MAX_INDEX_BYTES + 1)
    except HTTPError as error:
        if error.code == HTTP_NOT_FOUND:
            message = (
                f"Пакет {package_name!r} не найден в репозитории "
                "(HTTP 404)"
            )
        else:
            message = f"Репозиторий вернул HTTP {error.code}: {url}"
        error.close()
        raise RepositoryError(message) from error
    except (URLError, OSError, HTTPException) as error:
        message = f"Не удалось загрузить {url}: {error}"
        raise RepositoryError(message) from error
    if len(data) > MAX_INDEX_BYTES:
        raise RepositoryError(
            "Файл индекса превышает допустимый размер 20 МиБ"
        )
    try:
        return data.decode("utf-8")
    except UnicodeError as error:
        raise RepositoryError("Индекс должен иметь кодировку UTF-8") from error


def parse_records(text: str, package_name: str) -> list[dict]:
    """Разобрать JSON Lines; проверить структуру и принадлежность пакету."""
    records = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (ValueError, RecursionError) as error:
            message = f"Строка индекса {number}: некорректный JSON"
            raise RepositoryError(message) from error
        validate_record(record, package_name, number)
        records.append(record)
    if not records:
        raise RepositoryError("Репозиторий вернул пустой индекс пакета")
    return records


def validate_record(record, package_name: str, number: int) -> None:
    """Проверить поля записи версии, необходимые для выбора релиза."""
    prefix = f"Строка индекса {number}"
    if not isinstance(record, dict):
        raise RepositoryError(f"{prefix}: ожидается JSON-объект")
    name = record.get("name")
    if not isinstance(name, str) or name.lower() != package_name.lower():
        raise RepositoryError(f"{prefix}: имя пакета не совпадает с запросом")
    if not isinstance(record.get("vers"), str):
        raise RepositoryError(f"{prefix}: отсутствует строковая версия vers")
    if not isinstance(record.get("yanked"), bool):
        raise RepositoryError(f"{prefix}: yanked должен быть true или false")
    schema = record.get("v", SUPPORTED_SCHEMAS[0])
    if type(schema) is not int:
        raise RepositoryError(f"{prefix}: v должен быть целым числом")


def stable_version_key(version: str) -> tuple[int, ...] | None:
    """Получить числовой SemVer-ключ; prerelease исключить из выбора."""
    match = VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise RepositoryError(f"Некорректная версия в индексе: {version!r}")
    if match.group(PRERELEASE_GROUP) is not None:
        return None
    return tuple(int(match.group(index)) for index in VERSION_COMPONENTS)


def select_release(records: list[dict]) -> dict:
    """Выбрать максимальную стабильную неотозванную версию схемы 1 или 2."""
    candidates = []
    for record in records:
        schema = record.get("v", SUPPORTED_SCHEMAS[0])
        if record["yanked"] or schema not in SUPPORTED_SCHEMAS:
            continue
        key = stable_version_key(record["vers"])
        if key is not None:
            candidates.append((key, record))
    if not candidates:
        raise RepositoryError("Нет доступной стабильной неотозванной версии")
    return max(candidates, key=lambda candidate: candidate[0])[1]


def required_text(value, field: str) -> str:
    """Проверить непустое однострочное строковое поле метаданных."""
    if not isinstance(value, str) or not value or not value.isprintable():
        message = f"Поле зависимости {field}: нужна непустая строка"
        raise RepositoryError(message)
    return value


def optional_text(value, field: str) -> str | None:
    """Проверить строковое поле, которое может отсутствовать или быть null."""
    return None if value is None else required_text(value, field)


def parse_dependency(data) -> Dependency:
    """Прочитать зависимость с учётом переименований и значений по умолчанию."""
    if not isinstance(data, dict):
        raise RepositoryError("Элемент deps должен быть JSON-объектом")
    alias = required_text(data.get("name"), "name")
    name = optional_text(data.get("package"), "package") or alias
    if not re.fullmatch(PACKAGE_PATTERN, name):
        raise RepositoryError("Недопустимое имя пакета в зависимости")
    requirement = required_text(data.get("req"), "req")
    kind = data.get("kind")
    if kind is None:
        kind = "normal"
    if kind not in ("normal", "build", "dev"):
        raise RepositoryError(
            "Поле зависимости kind: нужен normal, build или dev"
        )
    optional = data.get("optional", False)
    if not isinstance(optional, bool):
        raise RepositoryError("Поле зависимости optional: нужен true или false")
    return Dependency(
        name, requirement, kind, optional,
        optional_text(data.get("target"), "target"),
        optional_text(data.get("registry"), "registry"),
    )


def load_package(repository: str, package_name: str) -> Package:
    """Загрузить пакет и вернуть прямые зависимости без транзитивного обхода."""
    records = parse_records(fetch_index(repository, package_name), package_name)
    release = select_release(records)
    deps = release.get("deps")
    if not isinstance(deps, list):
        raise RepositoryError("Поле deps выбранной версии должно быть массивом")
    dependencies = tuple(parse_dependency(item) for item in deps)
    return Package(release["name"], release["vers"], dependencies)


def format_dependency(dependency: Dependency) -> str:
    """Сформировать строку с именем, требованием версии и признаками ребра."""
    details = [dependency.kind]
    if dependency.optional:
        details.append("optional")
    if dependency.target is not None:
        details.append(f"target={dependency.target}")
    if dependency.registry is not None:
        details.append(f"registry={dependency.registry}")
    return (
        f"- {dependency.name} {dependency.requirement} "
        f"[{'; '.join(details)}]"
    )
