"""CLI второго этапа: загрузка и вывод прямых зависимостей Cargo."""

import argparse
import sys
from pathlib import Path

from cargo import RepositoryError, format_dependency, load_package
from config import ConfigError, load_config

CONFIG_ERROR_EXIT_CODE = 2
REPOSITORY_ERROR_EXIT_CODE = 3


def main(argv=None) -> int:
    """Прочитать CSV, загрузить зависимости и вывести результат или ошибку."""
    parser = argparse.ArgumentParser(
        description="Прямые зависимости пакетов Cargo, этап 2."
    )
    parser.add_argument("config", type=Path, help="путь к CSV-конфигурации")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as error:
        print(f"Ошибка конфигурации: {error}", file=sys.stderr)
        return CONFIG_ERROR_EXIT_CODE
    try:
        if config.test_mode:
            raise RepositoryError(
                "Тестовый репозиторий будет поддержан на этапе 3"
            )
        package = load_package(config.repository, config.package_name)
    except RepositoryError as error:
        print(f"Ошибка репозитория: {error}", file=sys.stderr)
        return REPOSITORY_ERROR_EXIT_CODE
    print(f"Пакет: {package.name} {package.version}")
    if package.dependencies:
        print("Прямые зависимости:")
        for dependency in package.dependencies:
            print(format_dependency(dependency))
    else:
        print("Прямых зависимостей нет.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
