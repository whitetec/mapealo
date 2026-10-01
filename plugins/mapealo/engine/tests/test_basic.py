import unittest
from tests._fx import write_app
from analyzer.basic import analyze_file


class TestAnalyzeFile(unittest.TestCase):
    def _analyze(self, src: str):
        d = write_app({"m.py": src})
        return analyze_file(d / "m.py", d)

    def test_functions_and_signatures(self):
        info = self._analyze(
            "def hello(a, b=1):\n"
            "    '''Saluda.'''\n"
            "    return a\n"
            "def _private():\n"
            "    pass\n"
        )
        sigs = [fn[0] for fn in info["fn"]]
        self.assertIn("hello(a, b)", sigs)
        self.assertNotIn("_private()", sigs)

    def test_route_decorator_flask_style(self):
        info = self._analyze(
            "@app.get('/users/{id}')\n"
            "def show(id):\n"
            "    '''Muestra usuario.'''\n"
            "    pass\n"
        )
        self.assertEqual(info["routes"], [["GET /users/{id}", "Muestra usuario."]])
        # No debe duplicarlo en fn
        self.assertEqual(info["fn"], [])

    def test_route_decorator_methods_kwarg(self):
        info = self._analyze(
            "@app.route('/x', methods=['POST', 'PUT'])\n"
            "def x(): pass\n"
        )
        self.assertEqual(info["routes"][0][0], "POST|PUT /x")

    def test_models_extract_columns(self):
        info = self._analyze(
            "class User(BaseModel):\n"
            "    id: int\n"
            "    name: str\n"
            "    _hidden: str = ''\n"
        )
        self.assertEqual(info["models"][0][0], "User")
        cols = info["models"][0][1]
        self.assertIn("id",   cols)
        self.assertIn("name", cols)
        self.assertNotIn("_hidden", cols)

    def test_module_constants(self):
        info = self._analyze(
            "PORT = 8080\n"
            "API_URL = 'https://example.com'\n"
            "x = 1   # no ALL_CAPS, no se captura\n"
        )
        names = [v[0] for v in info["vars"]]
        self.assertIn("PORT", names)
        self.assertIn("API_URL", names)
        self.assertNotIn("x", names)

    def test_syntax_error_safe(self):
        info = self._analyze("def f(:\n pass")
        self.assertEqual(info, {"fn": [], "models": [], "routes": [], "vars": [], "tags": []})


if __name__ == "__main__":
    unittest.main()


class TestAsyncDef(unittest.TestCase):
    """`async def` es AsyncFunctionDef y no hereda de FunctionDef. Mirando solo
    FunctionDef, anubis quedaba con 203 funciones y sus 83 rutas invisibles."""

    def _analyze(self, src: str):
        d = write_app({"m.py": src})
        return analyze_file(d / "m.py", d)

    def test_funcion_async_se_lista(self):
        info = self._analyze(
            "async def traer(cid):\n"
            '    """Trae la licitacion."""\n'
            "    return cid\n"
        )
        self.assertEqual([f[0] for f in info["fn"]], ["traer(cid)"])
        self.assertEqual(info["fn"][0][1], "Trae la licitacion.")

    def test_ruta_en_handler_async(self):
        info = self._analyze(
            "@router.get('/licitaciones')\n"
            "async def listar(request):\n"
            "    return []\n"
        )
        self.assertEqual([r[0] for r in info["routes"]], ["GET /licitaciones"])
        self.assertEqual(info["fn"], [])   # la ruta no se duplica como funcion

    def test_async_privada_se_ignora(self):
        info = self._analyze("async def _oculta():\n    pass\n")
        self.assertEqual(info["fn"], [])


class TestRutaRaizDeRouter(unittest.TestCase):
    def _analyze(self, src: str):
        d = write_app({"m.py": src})
        return analyze_file(d / "m.py", d)

    def test_path_vacio_es_la_portada_de_la_seccion(self):
        """`router.get('')` sobre un router montado en /admin es GET /admin."""
        info = self._analyze("@router.get('')\nasync def panel():\n    pass\n")
        self.assertEqual([r[0] for r in info["routes"]], ["GET /"])

    def test_decorador_sin_path_no_es_ruta(self):
        info = self._analyze("@app.get\ndef x():\n    pass\n")
        self.assertEqual(info["routes"], [])

    def test_path_por_keyword(self):
        info = self._analyze("@router.post(path='/crear')\nasync def c():\n    pass\n")
        self.assertEqual([r[0] for r in info["routes"]], ["POST /crear"])
