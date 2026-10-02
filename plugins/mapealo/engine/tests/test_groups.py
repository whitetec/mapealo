import unittest

from analyzer.builder import GROUP_ROOT, build_graph, build_groups, group_of
from analyzer.wp.builder import build_wp_graph
from analyzer.agents.builder import build_agents_graph


def _mods(*rels):
    return [{"id": r[:-3], "label": r.split("/")[-1], "rel_path": r} for r in rels]


class TestBuildGroups(unittest.TestCase):
    def test_arbol_de_directorios_reales(self):
        gs = build_groups(_mods(
            "app.py", "analyzer/detect.py", "analyzer/wp/builder.py",
        ), "demo")
        byid = {g["id"]: g for g in gs}
        self.assertEqual(byid[GROUP_ROOT]["parent"], None)
        self.assertEqual(byid["analyzer"]["parent"], GROUP_ROOT)
        self.assertEqual(byid["analyzer/wp"]["parent"], "analyzer")
        self.assertEqual(byid["analyzer/wp"]["depth"], 2)
        self.assertEqual(byid["analyzer/wp"]["label"], "wp")

    def test_un_grupo_por_directorio_aunque_haya_varios_archivos(self):
        gs = build_groups(_mods("a/x.py", "a/y.py", "a/z.py"), "demo")
        self.assertEqual(len(gs), 2)   # raíz + "a"

    def test_los_de_primer_nivel_tienen_color(self):
        gs = build_groups(_mods("a/x.py", "b/y.py"), "demo")
        top = [g for g in gs if g["depth"] == 1]
        self.assertTrue(all(g.get("color") for g in top))
        self.assertNotEqual(top[0]["color"], top[1]["color"])

    def test_group_of(self):
        self.assertEqual(group_of("analyzer/wp/builder.py"), "analyzer/wp")
        self.assertEqual(group_of("app.py"), GROUP_ROOT)


class TestGraphEmiteGroups(unittest.TestCase):
    """Los tres builders emiten la misma forma genérica: la vista de
    contención no puede tener que saber de qué kind viene el mapa."""

    def test_python(self):
        g = build_graph(_mods("app.py", "analyzer/wp/builder.py"), {}, [], "demo")
        self.assertTrue(g["groups"])
        hijo = next(c for c in g["children"] if c["id"] == "analyzer/wp/builder")
        self.assertEqual(hijo["group"], "analyzer/wp")

    def test_wordpress(self):
        comps = [{"id": "p1", "label": "Plugin uno", "rel_path": "wp-content/plugins/p1"}]
        g = build_wp_graph(comps, {"p1": "plugins"}, [], "sitio")
        ids = {gr["id"] for gr in g["groups"]}
        self.assertIn(GROUP_ROOT, ids)
        self.assertIn("plugins", ids)
        self.assertEqual(g["children"][0]["group"], "plugins")

    def test_agents(self):
        comps = [{"id": "jarvis-dev", "label": "WP-Copilot"}]
        g = build_agents_graph(comps, {"jarvis-dev": "T"}, [], "agentes")
        ids = {gr["id"] for gr in g["groups"]}
        self.assertIn(GROUP_ROOT, ids)
        self.assertIn("T", ids)
        self.assertEqual(g["children"][0]["group"], "T")


class TestSinNodosFantasma(unittest.TestCase):
    def test_homonimos_son_nodos_distintos(self):
        """Con el stem como id, estos tres eran un solo nodo dibujado 3 veces."""
        g = build_graph(_mods(
            "analyzer/builder.py",
            "analyzer/wp/builder.py",
            "analyzer/agents/builder.py",
        ), {}, [], "demo")
        ids = [c["id"] for c in g["children"]]
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(set(ids)), 3)


if __name__ == "__main__":
    unittest.main()
