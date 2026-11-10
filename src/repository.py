"""Источники прямых зависимостей: индекс Cargo или тестовый JSON-граф."""

import json
import re
from functools import partial
from pathlib import Path

from cargo import RepositoryError, load_package
from config import Config, resolve_path
from graph import DependencyLoader, Graph, is_filtered

TEST_NAME_PATTERN = r"[A-Z]+"
CRATES_GIT_INDEX = "https://github.com/rust-lang/crates.io-index"
CRATES_HTTP_INDEX = "https://index.crates.io"


def unique_object(pairs: list[tuple]) -> dict:
    """Отклонить повторные имена в JSON вместо молчаливой перезаписи."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise RepositoryError(f"Повторное имя пакета в JSON: {key!r}")
        result[key] = value
    return result


def validate_test_name(name: str) -> None:
    """Разрешить тестовые имена только из заглавных латинских букв."""
    if not isinstance(name, str) or not re.fullmatch(TEST_NAME_PATTERN, name):
        raise RepositoryError("Имена тестовых пакетов должны состоять из A-Z")


def validate_test_repository(data) -> Graph:
    """Проверить объект списков смежности и наличие описаний всех пакетов."""
    if not isinstance(data, dict):
        raise RepositoryError("Тестовый репозиторий должен быть JSON-объектом")
    graph = {
        name: validate_test_dependencies(name, dependencies)
        for name, dependencies in data.items()
    }
    references = {
        item for dependencies in graph.values() for item in dependencies
    }
    missing = references - graph.keys()
    if missing:
        names = ", ".join(sorted(missing))
        raise RepositoryError(f"Нет описаний тестовых пакетов: {names}")
    return graph



def validate_test_dependencies(name: str, dependencies) -> tuple[str, ...]:
    """Проверить имя вершины и список имён её прямых зависимостей."""
    validate_test_name(name)
    if not isinstance(dependencies, list):
        raise RepositoryError(f"Зависимости {name} должны быть массивом")
    for dependency in dependencies:
        validate_test_name(dependency)
    return tuple(dict.fromkeys(dependencies))


def load_test_repository(path: Path) -> Graph:
    """Прочитать UTF-8 JSON с необязательным BOM и проверить граф."""
    try:
        with path.open(encoding="utf-8-sig") as stream:
            data = json.load(stream, object_pairs_hook=unique_object)
    except (
        OSError, UnicodeError, json.JSONDecodeError, RecursionError,
    ) as error:
        message = f"Не удалось прочитать тестовый репозиторий: {error}"
        raise RepositoryError(message) from error
    return validate_test_repository(data)


def test_dependencies(graph: Graph, name: str) -> tuple[str, ...]:
    """Получить зависимости тестового пакета либо сообщить об отсутствии."""
    validate_test_name(name)
    if name not in graph:
        message = f"Пакет {name!r} не найден в тестовом репозитории"
        raise RepositoryError(message)
    return graph[name]


def normalize_registry(url: str) -> str:
    """Сопоставить HTTP и Git-адреса одного реестра crates.io."""
    normalized = url.removeprefix("sparse+").rstrip("/")
    if normalized == CRATES_GIT_INDEX:
        return CRATES_HTTP_INDEX
    return normalized


def validate_dependency_registry(registry: str | None, repository: str) -> None:
    """Не подменять внешний реестр URL-адресом выбранного репозитория."""
    if registry is not None:
        if normalize_registry(registry) != normalize_registry(repository):
            raise RepositoryError("Зависимость находится в другом реестре")


def cargo_dependencies(
    repository: str, name: str, substring: str = "",
) -> tuple[str, ...]:
    """Получить имена зависимостей Cargo, исключая совпавшие с фильтром."""
    package = load_package(repository, name)
    names = []
    for dependency in package.dependencies:
        name = dependency.name.lower()
        if is_filtered(name, substring):
            continue
        validate_dependency_registry(dependency.registry, repository)
        names.append(name)
    return tuple(names)


def create_loader(config: Config, base: Path) -> DependencyLoader:
    """Выбрать источник; разрешить путь JSON относительно конфигурации CSV."""
    if config.test_mode:
        path = resolve_path(config.repository, base)
        graph = load_test_repository(path)
        return partial(test_dependencies, graph)
    return partial(
        cargo_dependencies, config.repository,
        substring=config.filter_substring,
    )
