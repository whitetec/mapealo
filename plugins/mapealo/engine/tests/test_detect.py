import unittest
from tests._fx import write_app
from analyzer.detect import (
    assign_pillar, detect_fastapi_routers, detect_flask_blueprints,
    detect_stack, find_python_modules,
)


class TestAssignPillar(unittest.TestCase):
    def test_dir_takes_precedence(self):
        # auth_login va a backbone por keyword, pero gui/auth_login.py debería ir a interfaz
        self.assertEqual(assign_pillar("auth_login", "gui/auth_login.py"), "interfaz")

    def test_keyword_fallback(self):
        self.assertEqual(assign_pillar("backup_runner", "src/backup_runner.py"), "servicios")

    def test_default_backbone(self):
        self.assertEqual(assign_pillar("foo", ""), "backbone")


class TestDetectStack(unittest.TestCase):
    def test_fastapi(self):
        d = write_app({"requirements.txt": "fastapi>=0.111\nuvicorn\n"})
        self.assertEqual(detect_stack(d), "python-fastapi")

    def test_flask(self):
        d = write_app({"requirements.txt": "flask>=3.0\n"})
        self.assertEqual(detect_stack(d), "python-flask")

    def test_python_only(self):
        d = write_app({"main.py": "x=1\n"})
        self.assertEqual(detect_stack(d), "python")


class TestFindPythonModules(unittest.TestCase):
    def test_skips_tests_and_init_and_pycache(self):
        d = write_app({
            "src/main.py":          "x=1",
            "src/__init__.py":      "",
            "tests/test_foo.py":    "",
            "venv/lib/x.py":        "",
            "src/utils.py":         "",
        })
        names = sorted(p.name for p in find_python_modules(d))
        self.assertEqual(names, ["main.py", "utils.py"])


class TestDetectFactoryCalls(unittest.TestCase):
    def test_blueprints_use_first_string_arg(self):
        d = write_app({
            "auth.py": "from flask import Blueprint\nbp = Blueprint('auth_bp', __name__)\n",
        })
        bps = detect_flask_blueprints(d)
        self.assertEqual(len(bps), 1)
        self.assertEqual(bps[0]["id"],  "auth_bp")
        self.assertEqual(bps[0]["var"], "bp")

    def test_routers_use_var_name(self):
        d = write_app({
            "api.py": "from fastapi import APIRouter\nrouter = APIRouter(prefix='/x')\n",
        })
        rts = detect_fastapi_routers(d)
        self.assertEqual(len(rts), 1)
        self.assertEqual(rts[0]["id"], "router")


if __name__ == "__main__":
    unittest.main()
