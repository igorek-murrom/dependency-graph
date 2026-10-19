"""CLI первого этапа: проверка и вывод конфигурации."""

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

from config import ConfigError, load_config

ERROR_EXIT_CODE = 2


def main(argv=None) -> int:
    """Прочитать путь к CSV, вывести параметры либо понятную ошибку."""
    parser = argparse.ArgumentParser(
        description="Прототип визуализатора зависимостей Cargo, этап 1."
    )
    parser.add_argument("config", type=Path, help="путь к CSV-конфигурации")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as error:
        print(f"Ошибка конфигурации: {error}", file=sys.stderr)
        return ERROR_EXIT_CODE
    for key, value in asdict(config).items():
        if isinstance(value, bool):
            value = str(value).lower()
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
