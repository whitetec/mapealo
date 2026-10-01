import unittest

from tests._fx import write_app
from analyzer.imports import (
    build_import_graph, build_module_index, dotted_name,
)


def _mods(*rels):
    """Módulos con id = ruta sin .py, como los arma run_basic."""
    return [{"id": r[:-3], "rel_path": r} for r in rels]


class TestDottedName(unittest.TestCase):
    def test_modulo_y_paquete(self):
        self.assertEqual(dotted_name("analyzer/wp/builder.py"), "analyzer.wp.builder")
        self.assertEqual(dotted_name("analyzer/wp/__init__.py"), "analyzer.wp")
        self.assertEqual(dotted_name("app.py"), "app")


class TestModuleIndex(unittest.TestCase):
    def test_sufijo_ambiguo_se_descarta(self):
        mods = _mods("analyzer/builder.py", "analyzer/wp/builder.py")
        exact, by_suffix = build_module_index(mods)
        self.assertIn("analyzer.builder", exact)
        self.assertIn("analyzer.wp.builder", exact)
        self.assertNotIn("builder", by_suffix)

    def test_sufijo_unico_se_registra(self):
        exact, by_suffix = build_module_index(_mods("src/main.py"))
        self.assertEqual(by_suffix.get("main"), "src/main")


class TestImportGraph(unittest.TestCase):
    def test_import_plano(self):
        """`import puente` es un edge; el analizador viejo solo leía ImportFrom."""
        d = write_app({
            "app.py":    "import puente\nimport json\n",
            "puente.py": "x = 1\n",
        })
        g = build_import_graph(_mods("app.py", "puente.py"), d)
        self.assertEqual(g, {"app": ["puente"]})

    def test_stdlib_y_terceros_no_generan_edge(self):
        d = write_app({"app.py": "import os\nimport fastapi\nfrom pathlib import Path\n"})
        self.assertEqual(build_import_graph(_mods("app.py"), d), {})

    def test_homonimos_no_se_mezclan(self):
        """El bug de fondo: dos builder.py eran un solo nodo."""
        d = write_app({
            "analyzer/builder.py":     "from .detect import X\n",
            "analyzer/detect.py":      "x = 1\n",
            "analyzer/wp/builder.py":  "from analyzer.wp.headers import parse\n",
            "analyzer/wp/headers.py":  "def parse(): pass\n",
        })
        g = build_import_graph(_mods(
            "analyzer/builder.py", "analyzer/detect.py",
            "analyzer/wp/builder.py", "analyzer/wp/headers.py",
        ), d)
        self.assertEqual(g["analyzer/builder"],    ["analyzer/detect"])
        self.assertEqual(g["analyzer/wp/builder"], ["analyzer/wp/headers"])

    def test_relativo_sube_de_paquete(self):
        d = write_app({
            "pkg/sub/mod.py": "from ..base import algo\n",
            "pkg/base.py":    "def algo(): pass\n",
        })
        g = build_import_graph(_mods("pkg/sub/mod.py", "pkg/base.py"), d)
        self.assertEqual(g, {"pkg/sub/mod": ["pkg/base"]})

    def test_from_paquete_import_submodulo(self):
        d = write_app({
            "app.py":            "from analyzer import detect\n",
            "analyzer/__init__.py": "",
            "analyzer/detect.py":   "x = 1\n",
        })
        g = build_import_graph(_mods("app.py", "analyzer/__init__.py", "analyzer/detect.py"), d)
        self.assertEqual(g["app"], ["analyzer/detect"])

    def test_from_paquete_import_funcion_cae_al_init(self):
        d = write_app({
            "app.py":               "from analyzer import detect_kind\n",
            "analyzer/__init__.py": "def detect_kind(): pass\n",
        })
        g = build_import_graph(_mods("app.py", "analyzer/__init__.py"), d)
        self.assertEqual(g["app"], ["analyzer/__init__"])

    def test_from_dot_import_modulo(self):
        d = write_app({
            "pkg/a.py":        "from . import b\n",
            "pkg/b.py":        "x = 1\n",
            "pkg/__init__.py": "",
        })
        g = build_import_graph(_mods("pkg/a.py", "pkg/b.py", "pkg/__init__.py"), d)
        self.assertEqual(g["pkg/a"], ["pkg/b"])

    def test_import_dentro_de_funcion(self):
        d = write_app({
            "app.py":     "def f():\n    from mapealo import generate\n",
            "mapealo.py": "def generate(): pass\n",
        })
        g = build_import_graph(_mods("app.py", "mapealo.py"), d)
        self.assertEqual(g["app"], ["mapealo"])

    def test_sin_auto_referencia(self):
        d = write_app({"app.py": "import app\n"})
        self.assertEqual(build_import_graph(_mods("app.py"), d), {})

    def test_archivo_roto_no_corta_la_corrida(self):
        d = write_app({
            "roto.py": "def (:\n",
            "app.py":  "import util\n",
            "util.py": "x = 1\n",
        })
        g = build_import_graph(_mods("roto.py", "app.py", "util.py"), d)
        self.assertEqual(g, {"app": ["util"]})

    def test_sin_imports_no_hay_edges(self):
        """Control negativo: si no importa nada, no puede aparecer un edge."""
        d = write_app({"a.py": "x = 1\n", "b.py": "y = 2\n"})
        self.assertEqual(build_import_graph(_mods("a.py", "b.py"), d), {})


if __name__ == "__main__":
    unittest.main()
