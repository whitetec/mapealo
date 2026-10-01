import unittest

from tests._fx import write_app
from analyzer.basic import analyze_file
from analyzer.detect import find_python_modules
from analyzer.secciones import build_secciones, resolver_urls


def _analizar(files: dict):
    """Corre el pipeline mínimo sobre una app sintética."""
    d = write_app(files)
    modules, detail = [], {}
    for f in find_python_modules(d):
        rel = str(f.relative_to(d))
        mid = rel[:-3]
        modules.append({"id": mid, "label": f.name, "rel_path": rel})
        detail[mid] = analyze_file(f, d)
    return d, modules, detail


def _urls(files: dict):
    d, modules, detail = _analizar(files)
    return {f"{u['method']} {u['url']}": u for u in resolver_urls(d, modules, detail)}


class TestFlask(unittest.TestCase):
    def test_prefijo_del_registro(self):
        u = _urls({
            "app/admin.py": "from flask import Blueprint\n"
                            "admin_bp = Blueprint('admin', __name__)\n"
                            "@admin_bp.route('/clients/new')\n"
                            "def nuevo(): pass\n",
            "app/main.py":  "from .admin import admin_bp\n"
                            "app.register_blueprint(admin_bp, url_prefix='/admin')\n",
        })
        self.assertIn("GET /admin/clients/new", u)
        self.assertTrue(u["GET /admin/clients/new"]["resuelto"])

    def test_el_registro_pisa_al_constructor(self):
        """Es lo que hace Flask: el url_prefix del registro gana."""
        u = _urls({
            "app/x.py":    "from flask import Blueprint\n"
                           "bp = Blueprint('x', __name__, url_prefix='/viejo')\n"
                           "@bp.route('/a')\n"
                           "def a(): pass\n",
            "app/main.py": "from .x import bp\n"
                           "app.register_blueprint(bp, url_prefix='/nuevo')\n",
        })
        self.assertIn("GET /nuevo/a", u)
        self.assertNotIn("GET /viejo/a", u)

    def test_alias_en_el_import(self):
        """`from .admin import bp as admin_bp`: los nombres no coinciden."""
        u = _urls({
            "app/admin.py": "from flask import Blueprint\n"
                            "bp = Blueprint('admin', __name__)\n"
                            "@bp.route('/panel')\n"
                            "def panel(): pass\n",
            "app/main.py":  "from .admin import bp as admin_bp\n"
                            "app.register_blueprint(admin_bp, url_prefix='/admin')\n",
        })
        self.assertIn("GET /admin/panel", u)

    def test_blueprint_declarado_en_otro_modulo(self):
        """`assets.py` decora con un blueprint definido en `cybersec.py`."""
        u = _urls({
            "app/cybersec.py": "from flask import Blueprint\n"
                               "cyber_bp = Blueprint('c', __name__)\n",
            "app/assets.py":   "from .cybersec import cyber_bp\n"
                               "@cyber_bp.route('/inventario')\n"
                               "def inv(): pass\n",
            "app/main.py":     "from .cybersec import cyber_bp\n"
                               "app.register_blueprint(cyber_bp, url_prefix='/cybersec')\n",
        })
        self.assertIn("GET /cybersec/inventario", u)

    def test_registro_sin_prefijo_va_a_la_raiz(self):
        u = _urls({
            "app/auth.py": "from flask import Blueprint\n"
                           "auth_bp = Blueprint('auth', __name__)\n"
                           "@auth_bp.route('/login')\n"
                           "def login(): pass\n",
            "app/main.py": "from .auth import auth_bp\n"
                           "app.register_blueprint(auth_bp)\n",
        })
        self.assertTrue(u["GET /login"]["resuelto"])


class TestFastAPI(unittest.TestCase):
    def test_prefijo_del_constructor(self):
        u = _urls({
            "app/routers/admin.py": "from fastapi import APIRouter\n"
                                    "router = APIRouter(prefix='/admin')\n"
                                    "@router.get('/usuarios')\n"
                                    "async def us(): pass\n",
            "app/main.py":          "from .routers import admin\n"
                                    "app.include_router(admin.router)\n",
        })
        self.assertIn("GET /admin/usuarios", u)

    def test_los_prefijos_se_concatenan(self):
        """En FastAPI el prefijo del include se suma al del router."""
        u = _urls({
            "app/routers/a.py": "from fastapi import APIRouter\n"
                                "router = APIRouter(prefix='/admin')\n"
                                "@router.get('/x')\n"
                                "async def x(): pass\n",
            "app/main.py":      "from .routers import a\n"
                                "app.include_router(a.router, prefix='/api')\n",
        })
        self.assertIn("GET /api/admin/x", u)

    def test_path_vacio_es_la_portada(self):
        u = _urls({
            "app/routers/a.py": "from fastapi import APIRouter\n"
                                "router = APIRouter(prefix='/alertas')\n"
                                "@router.get('')\n"
                                "async def mias(): pass\n",
            "app/main.py":      "from .routers import a\n"
                                "app.include_router(a.router)\n",
        })
        self.assertIn("GET /alertas", u)


class TestSinResolver(unittest.TestCase):
    def test_blueprint_que_nadie_registra_no_se_monta_en_la_raiz(self):
        """Control negativo. Sin esto, una falla de resolución se ve idéntica
        a un blueprint montado en la raíz y no se detecta nunca."""
        u = _urls({
            "app/huerfano.py": "from flask import Blueprint\n"
                               "bp = Blueprint('h', __name__)\n"
                               "@bp.route('/perdida')\n"
                               "def p(): pass\n",
        })
        self.assertFalse(u["GET /perdida"]["resuelto"])

    def test_ruta_sobre_la_app_directa_es_absoluta(self):
        u = _urls({"main.py": "@app.get('/salud')\ndef s(): pass\n"})
        self.assertTrue(u["GET /salud"]["resuelto"])


class TestArbol(unittest.TestCase):
    def _arbol(self, files):
        d, modules, detail = _analizar(files)
        return build_secciones(d, modules, detail)

    def test_las_secciones_son_los_tramos_de_la_url(self):
        s = self._arbol({
            "app/admin.py": "from flask import Blueprint\n"
                            "bp = Blueprint('a', __name__)\n"
                            "@bp.route('/usuarios/nuevo')\n"
                            "def n(): pass\n",
            "app/main.py":  "from .admin import bp\n"
                            "app.register_blueprint(bp, url_prefix='/admin')\n",
        })
        ids = {g["id"] for g in s["groups"]}
        self.assertIn("/admin", ids)
        self.assertIn("/admin/usuarios", ids)
        self.assertEqual(s["children"][0]["group"], "/admin/usuarios")
        self.assertEqual(s["children"][0]["label"], "GET nuevo")

    def test_la_hoja_lleva_archivo_y_funcion(self):
        """Es lo que permite que un clic referencie el rango exacto."""
        s = self._arbol({
            "app/admin.py": "from flask import Blueprint\n"
                            "bp = Blueprint('a', __name__)\n"
                            "@bp.route('/x')\n"
                            "def manejar(): pass\n",
            "app/main.py":  "from .admin import bp\n"
                            "app.register_blueprint(bp, url_prefix='/admin')\n",
        })
        hoja = s["children"][0]
        self.assertEqual(hoja["rel_path"], "app/admin.py")
        self.assertEqual(hoja["fn"], "manejar")

    def test_lo_no_resuelto_queda_marcado(self):
        s = self._arbol({
            "app/h.py": "from flask import Blueprint\n"
                        "bp = Blueprint('h', __name__)\n"
                        "@bp.route('/perdida')\n"
                        "def p(): pass\n",
        })
        self.assertIn("?", [g["label"] for g in s["groups"]])
        self.assertIn("sin resolver", s["children"][0]["tags"])

    def test_app_sin_rutas_no_tiene_arbol(self):
        self.assertEqual(self._arbol({"m.py": "def x(): pass\n"}), {})


if __name__ == "__main__":
    unittest.main()
