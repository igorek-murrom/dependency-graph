"""Построение графа зависимостей обходом DFS без рекурсии."""

from collections.abc import Callable

Graph = dict[str, tuple[str, ...]]
DependencyLoader = Callable[[str], tuple[str, ...]]


def is_filtered(name: str, substring: str) -> bool:
    """Проверить исключение пакета по непустой подстроке с учётом регистра."""
    return bool(substring) and substring in name


def build_graph(
    root: str, load: DependencyLoader, substring: str = "",
) -> Graph:
    """Обойти достижимые пакеты стеком, сохраняя связи и пропуская повторы."""
    graph = {}
    stack = [root]
    while stack:
        name = stack.pop()
        if name in graph or is_filtered(name, substring):
            continue
        dependencies = tuple(dict.fromkeys(
            dependency for dependency in load(name)
            if not is_filtered(dependency, substring)
        ))
        graph[name] = dependencies
        stack.extend(reversed(dependencies))
    return graph


def print_graph(graph: Graph) -> None:
    """Вывести списки смежности в порядке посещения DFS."""
    if not graph:
        print("Граф пуст: корневой пакет исключён фильтром.")
        return
    print("Граф зависимостей (DFS):")
    for name, dependencies in graph.items():
        targets = ", ".join(dependencies) or "нет зависимостей"
        print(f"{name} -> {targets}")
