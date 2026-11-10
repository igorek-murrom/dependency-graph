"""Порядок загрузки зависимостей: завершение DFS без рекурсии."""

from graph import Graph


class GraphError(ValueError):
    """Граф не допускает корректного порядка загрузки."""


def dependency_order(graph: Graph) -> tuple[str, ...]:
    """Выдать зависимости перед пакетами; проверить циклы и наличие узлов."""
    order = []
    visited = set()
    active = set()
    stack = [(name, False) for name in reversed(graph)]
    while stack:
        name, finished = stack.pop()
        if finished:
            active.remove(name)
            visited.add(name)
            order.append(name)
            continue
        if name in visited:
            continue
        if name in active:
            message = f"Цикл с пакетом {name!r}: порядок загрузки невозможен"
            raise GraphError(message)
        if name not in graph:
            raise GraphError(f"Нет описания пакета {name!r}")
        active.add(name)
        stack.append((name, True))
        stack.extend(
            (dependency, False) for dependency in reversed(graph[name])
        )
    return tuple(order)


def print_order(order: tuple[str, ...]) -> None:
    """Вывести порядок, включая корень, либо результат исключения корня."""
    if not order:
        print("Порядок загрузки пуст: корневой пакет исключён фильтром.")
        return
    print("Порядок загрузки (зависимости перед пакетом):")
    print(" -> ".join(order))
