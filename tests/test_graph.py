"""Проверки нерекурсивного DFS, фильтрации и циклов."""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, call

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cargo import RepositoryError
from graph import build_graph, is_filtered, print_graph

DEEP_CHAIN_MARGIN = 100


class GraphTests(unittest.TestCase):
    """Проверить обход на небольших графах и глубокой цепочке."""

    def walk(self, source, root="A", substring=""):
        """Построить граф и вернуть источник для проверки числа обращений."""
        load = Mock(side_effect=source.__getitem__)
        return build_graph(root, load, substring), load

    def test_transitive_chain(self):
        """Обойти зависимости зависимостей до листа."""
        source = {"A": ("B",), "B": ("C",), "C": ()}
        graph, load = self.walk(source)
        self.assertEqual(graph, source)
        self.assertEqual(load.call_args_list, [call("A"), call("B"), call("C")])

    def test_depth_first_order(self):
        """Посетить общую зависимость по первой ветви, а не в ширину."""
        source = {"A": ("B", "C"), "B": ("D",), "C": ("D",), "D": ()}
        graph, load = self.walk(source)
        self.assertEqual(list(graph), ["A", "B", "D", "C"])
        self.assertEqual(graph["C"], ("D",))
        self.assertEqual(load.call_args_list,
                         [call("A"), call("B"), call("D"), call("C")])

    def test_cycle(self):
        """Сохранить обратное ребро и завершить обход циклического графа."""
        source = {"A": ("B",), "B": ("C",), "C": ("A",)}
        graph, load = self.walk(source)
        self.assertEqual(graph, source)
        self.assertEqual(load.call_count, len(source))

    def test_self_cycle(self):
        """Петля пакета на себя не должна повторно загружать этот пакет."""
        graph, load = self.walk({"A": ("A",)})
        self.assertEqual(graph, {"A": ("A",)})
        load.assert_called_once_with("A")

    def test_disconnected_nodes(self):
        """Обходить только вершины, достижимые из корня."""
        graph, load = self.walk({"A": ("B",), "B": (), "Z": ()})
        self.assertEqual(list(graph), ["A", "B"])
        self.assertEqual(load.call_args_list, [call("A"), call("B")])

    def test_leaf(self):
        """Сохранить корень без зависимостей как отдельную вершину."""
        graph, load = self.walk({"A": ()})
        self.assertEqual(graph, {"A": ()})
        load.assert_called_once_with("A")

    def test_duplicate_edges(self):
        """Убрать дубли рёбер, сохранив порядок первого появления."""
        graph, load = self.walk({"A": ("B", "B", "C"), "B": (), "C": ()})
        self.assertEqual(graph["A"], ("B", "C"))
        self.assertEqual(load.call_args_list, [call("A"), call("B"), call("C")])

    def test_filter_prunes_branch(self):
        """Исключённый пакет не должен попадать ни в рёбра, ни в загрузку."""
        graph, load = self.walk({"A": ("B", "C"), "C": ()}, substring="B")
        self.assertEqual(graph, {"A": ("C",), "C": ()})
        self.assertEqual(load.call_args_list, [call("A"), call("C")])

    def test_filter_keeps_shared_dependency(self):
        """Сохранить общий пакет, достижимый по оставшейся ветви."""
        source = {"A": ("B", "C"), "B": ("D",), "C": ("D",), "D": ()}
        graph, load = self.walk(source, substring="B")
        self.assertEqual(graph, {"A": ("C",), "C": ("D",), "D": ()})
        self.assertEqual(load.call_args_list, [call("A"), call("C"), call("D")])

    def test_filter_root(self):
        """Исключение корня даёт пустой граф без обращения к источнику."""
        graph, load = self.walk({}, substring="A")
        self.assertEqual(graph, {})
        load.assert_not_called()

    def test_filter_rules(self):
        """Пустой фильтр отключён; непустой ищется как подстрока с регистром."""
        self.assertFalse(is_filtered("ABC", ""))
        self.assertTrue(is_filtered("ABC", "B"))
        self.assertFalse(is_filtered("ABC", "b"))

    def test_deep_chain(self):
        """Пройти цепочку длиннее лимита рекурсии Python без RecursionError."""
        length = sys.getrecursionlimit() + DEEP_CHAIN_MARGIN
        source = {str(index): (str(index + 1),) for index in range(length)}
        source[str(length)] = ()
        graph, load = self.walk(source, root="0")
        self.assertEqual(graph, source)
        self.assertEqual(load.call_count, len(source))

    def test_loader_failure(self):
        """Передать ошибку зависимого пакета вызывающему коду."""
        load = Mock(side_effect=[("B",), RepositoryError("не найден B")])
        with self.assertRaisesRegex(RepositoryError, "B"):
            build_graph("A", load)

    def test_print_graph(self):
        """Печатать списки смежности с явными листьями."""
        output = io.StringIO()
        with redirect_stdout(output):
            print_graph({"A": ("B",), "B": ()})
        self.assertEqual(output.getvalue().splitlines(), [
            "Граф зависимостей (DFS):", "A -> B", "B -> нет зависимостей",
        ])

    def test_print_empty_graph(self):
        """Пустой граф после фильтрации должен иметь понятное сообщение."""
        output = io.StringIO()
        with redirect_stdout(output):
            print_graph({})
        self.assertIn("корневой пакет исключён", output.getvalue())


if __name__ == "__main__":
    unittest.main()
