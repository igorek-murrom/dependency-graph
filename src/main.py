"""CLI третьего этапа: построение и вывод графа зависимостей."""

import argparse
import sys
from pathlib import Path

from cargo import RepositoryError
from config import Config, ConfigError, load_config
from graph import Graph, build_graph, print_graph
from repository import create_loader

CONFIG_ERROR_EXIT_CODE = 2
REPOSITORY_ERROR_EXIT_CODE = 3


def analyze(config: Config, config_path: Path) -> Graph:
    """Выбрать источник и построить граф с фильтром из CSV."""
    load = create_loader(config, config_path.resolve().parent)
    name = config.package_name
    if not config.test_mode:
        name = name.lower()
    return build_graph(name, load, config.filter_substring)


def main(argv=None) -> int:
    """Прочитать CSV, построить граф и вывести результат либо ошибку."""
    parser = argparse.ArgumentParser(
        description="Граф зависимостей Cargo, этап 3: DFS без рекурсии."
    )
    parser.add_argument("config", type=Path, help="путь к CSV-конфигурации")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as error:
        print(f"Ошибка конфигурации: {error}", file=sys.stderr)
        return CONFIG_ERROR_EXIT_CODE
    try:
        graph = analyze(config, args.config)
    except RepositoryError as error:
        print(f"Ошибка репозитория: {error}", file=sys.stderr)
        return REPOSITORY_ERROR_EXIT_CODE
    print_graph(graph)
    return 0


if __name__ == "__main__":
    sys.exit(main())
