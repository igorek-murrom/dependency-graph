"""Проверки порядка загрузки зависимостей на основе итеративного DFS."""

import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from order import GraphError, dependency_order, print_order

DEEP_CHAIN_MARGIN = 100


class OrderTests(unittest.TestCase):
    """Проверить зависимости перед пакетами, циклы и глубокий граф."""

    def assert_valid_order(self, graph, order):
        """Проверить каждое ребро и отсутствие пропущенных или лишних вершин."""
        self.assertEqual(set(order), set(graph))
        self.assertEqual(len(order), len(graph))
        positions = {name: index for index, name in enumerate(order)}
        for name, dependencies in graph.items():
            for dependency in dependencies:
                self.assertLess(positions[dependency], positions[name])

    def test_chain(self):
        """Загрузить всю цепочку от листа до корня."""
        graph = {"A": ("B",), "B": ("C",), "C": ()}
        order = dependency_order(graph)
        self.assertEqual(order, ("C", "B", "A"))
        self.assert_valid_order(graph, order)

    def test_diamond(self):
        """Общая зависимость появляется один раз и раньше обоих потребителей."""
        graph = {"A": ("B", "C"), "B": ("D",), "D": (), "C": ("D",)}
        order = dependency_order(graph)
        self.assertEqual(order, ("D", "B", "C", "A"))
        self.assert_valid_order(graph, order)

    def test_cross_edge_to_pending_sibling(self):
        """Ребро к ещё не посещённой соседней ветви не является циклом."""
        graph = {"A": ("B", "C"), "B": ("C",), "C": ()}
        order = dependency_order(graph)
        self.assertEqual(order, ("C", "B", "A"))
        self.assert_valid_order(graph, order)

    def test_duplicate_edges(self):
        """Повторные рёбра не должны повторять загрузку одного пакета."""
        graph = {"A": ("B", "B"), "B": ()}
        order = dependency_order(graph)
        self.assertEqual(order, ("B", "A"))
        self.assert_valid_order(graph, order)

    def test_key_order_does_not_replace_dependencies(self):
        """Результат остаётся корректным при ином порядке ключей словаря."""
        graph = {"C": (), "A": ("B",), "B": ("C",)}
        self.assert_valid_order(graph, dependency_order(graph))

    def test_multiple_roots(self):
        """Обработать несколько компонент переданного графа."""
        graph = {"A": ("B",), "B": (), "X": ("Y",), "Y": ()}
        self.assert_valid_order(graph, dependency_order(graph))

    def test_leaf_and_empty(self):
        """Поддержать пакет без зависимостей и граф после исключения корня."""
        self.assertEqual(dependency_order({"A": ()}), ("A",))
        self.assertEqual(dependency_order({}), ())

    def test_cycles(self):
        """Для петли и многовершинного цикла корректного порядка нет."""
        cases = (
            {"A": ("A",)},
            {"A": ("B",), "B": ("A",)},
            {"A": ("B",), "B": ("C",), "C": ("A",)},
        )
        for graph in cases:
            with self.subTest(graph=graph):
                with self.assertRaisesRegex(GraphError, "Цикл"):
                    dependency_order(graph)

    def test_missing_node(self):
        """Отсутствие описания зависимости не должно приводить к KeyError."""
        with self.assertRaisesRegex(GraphError, "B"):
            dependency_order({"A": ("B",)})

    def test_deep_graph(self):
        """Получить порядок для цепочки длиннее лимита рекурсии Python."""
        length = sys.getrecursionlimit() + DEEP_CHAIN_MARGIN
        graph = {str(index): (str(index + 1),) for index in range(length)}
        graph[str(length)] = ()
        order = dependency_order(graph)
        self.assertEqual(order[0], str(length))
        self.assertEqual(order[-1], "0")
        self.assert_valid_order(graph, order)

    def test_input_is_unchanged(self):
        """Вычисление порядка не должно менять исходный граф."""
        graph = {"A": ("B",), "B": ()}
        original = graph.copy()
        dependency_order(graph)
        self.assertEqual(graph, original)

    def test_print_order(self):
        """Печатать порядок в направлении от зависимостей к корню."""
        output = io.StringIO()
        with redirect_stdout(output):
            print_order(("C", "B", "A"))
        self.assertEqual(output.getvalue().splitlines(), [
            "Порядок загрузки (зависимости перед пакетом):", "C -> B -> A",
        ])

    def test_print_empty_order(self):
        """Объяснить отсутствие порядка при исключении корня фильтром."""
        output = io.StringIO()
        with redirect_stdout(output):
            print_order(())
        self.assertIn("корневой пакет исключён", output.getvalue())


class OrderCliTests(unittest.TestCase):
    """Проверить демонстрационные CSV через отдельный процесс."""

    def run_cli(self, example):
        """Запустить CLI из другой папки с абсолютным путём к настройкам."""
        root = Path(__file__).resolve().parents[1]
        return subprocess.run(
            [sys.executable, str(root / "src/main.py"),
             str(root / "examples" / example)],
            cwd=root.parent, capture_output=True, text=True, check=False,
        )

    def test_examples(self):
        """Проверить цепочку, общую зависимость, фильтр и отдельный пакет."""
        cases = {
            "order-config.csv": "C -> B -> A",
            "order-diamond-config.csv": "D -> B -> C -> A",
            "order-filter-config.csv": "D -> C -> A",
            "order-leaf-config.csv": "C",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                result = self.run_cli(name)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(result.stdout.splitlines()[-1], expected)

    def test_cycle_error(self):
        """При цикле не выводить частичный или некорректный порядок."""
        result = self.run_cli("order-cycle-config.csv")
        self.assertEqual(result.returncode, 4)
        self.assertEqual(result.stdout, "")
        self.assertIn("порядок загрузки невозможен", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_invalid_mode(self):
        """Неверное значение нового CSV-параметра должно давать ошибку 2."""
        result = self.run_cli("errors/load_order.csv")
        self.assertEqual(result.returncode, 2)
        self.assertIn("load_order", result.stderr)

    def test_root_filter(self):
        """Исключение корня должно завершаться успешно с пояснением."""
        result = self.run_cli("order-root-filter-config.csv")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Порядок загрузки пуст", result.stdout)


if __name__ == "__main__":
    unittest.main()
