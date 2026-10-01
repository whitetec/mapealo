"""Tests de la resolución portable de raíces — paths.py."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from _fx import write_app  # noqa: F401  (asegura jarvis-map en sys.path)

import paths


class _HomeFixture(unittest.TestCase):
    """Cada test corre sobre un HOME propio: `paths` lee el entorno, así que
    aislarlo es lo que permite testear la autodetección sin tocar el real."""

    def setUp(self):
        self.tmp   = Path(tempfile.mkdtemp(prefix="jmap-home-"))
        self._envs = {}
        for k, v in (
            ("HOME", str(self.tmp)),
            ("XDG_CONFIG_HOME", str(self.tmp / ".config")),
            ("XDG_DATA_HOME", str(self.tmp / ".local/share")),
            ("JARVIS_MAP_APPS_DIR", ""),
            ("CLAUDE_CONFIG_DIR", ""),
        ):
            self._envs[k] = os.environ.get(k)
            if v:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._envs.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def mkproject(self, rel: str, marker: str = "requirements.txt") -> Path:
        d = self.tmp / rel
        d.mkdir(parents=True, exist_ok=True)
        (d / marker).write_text("", encoding="utf-8")
        return d


class TestAutodetect(_HomeFixture):

    def test_detecta_raiz_jarvis(self):
        self.mkproject("jarvis-apps/apps/mi-app")
        self.assertEqual(paths.apps_roots(), [self.tmp / "jarvis-apps/apps"])

    def test_detecta_raices_genericas(self):
        self.mkproject("proyectos/alfa")
        self.mkproject("dev/beta", marker="package.json")
        roots = paths.apps_roots()
        self.assertIn(self.tmp / "proyectos", roots)
        self.assertIn(self.tmp / "dev", roots)

    def test_raiz_sin_proyectos_no_cuenta(self):
        """Un directorio con nombre candidato pero sin marcadores de proyecto
        adentro no es una raíz: evita tomar `~/src` de un tarball cualquiera."""
        (self.tmp / "src/notas").mkdir(parents=True)
        self.assertEqual(paths.apps_roots(), [])

    def test_env_tiene_prioridad(self):
        self.mkproject("proyectos/alfa")
        externa = self.tmp / "externa"
        (externa / "gamma").mkdir(parents=True)
        os.environ["JARVIS_MAP_APPS_DIR"] = str(externa)
        self.assertEqual(paths.apps_roots()[0], externa)

    def test_env_acepta_varias_raices(self):
        a, b = self.tmp / "ra", self.tmp / "rb"
        a.mkdir(); b.mkdir()
        os.environ["JARVIS_MAP_APPS_DIR"] = os.pathsep.join([str(a), str(b)])
        self.assertEqual(paths.apps_roots()[:2], [a, b])

    def test_config_de_usuario(self):
        externa = self.tmp / "desde-config"
        externa.mkdir()
        cfg = paths.user_config()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"apps_dirs": [str(externa)]}), encoding="utf-8")
        self.assertIn(externa, paths.apps_roots())

    def test_config_ilegible_no_rompe(self):
        cfg = paths.user_config()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("{ esto no es json", encoding="utf-8")
        self.assertEqual(paths.apps_roots(), [])


class TestResolucion(_HomeFixture):

    def test_resuelve_por_id(self):
        d = self.mkproject("jarvis-apps/apps/mi-app")
        self.assertEqual(paths.resolve_app_dir("mi-app"), d)

    def test_resuelve_por_ruta_absoluta(self):
        d = self.mkproject("cualquier/lado/suelta")
        self.assertEqual(paths.resolve_app_dir(str(d)), d)

    def test_resuelve_por_tilde(self):
        self.mkproject("otra/app-x")
        self.assertEqual(paths.resolve_app_dir("~/otra/app-x"), self.tmp / "otra/app-x")

    def test_id_inexistente_es_none(self):
        self.assertIsNone(paths.resolve_app_dir("no-existe"))

    def test_id_con_traversal_es_none(self):
        self.assertIsNone(paths.resolve_app_dir("..%2Fetc"))
        self.assertFalse(paths.is_app_id("../etc"))

    def test_app_id_para_ruta_es_el_basename(self):
        d = self.mkproject("x/y/zeta")
        self.assertEqual(paths.app_id_for(str(d)), "zeta")
        self.assertEqual(paths.app_id_for("mi-app"), "mi-app")

    def test_list_apps_omite_privados(self):
        self.mkproject("jarvis-apps/apps/visible")
        (self.tmp / "jarvis-apps/apps/_template").mkdir(parents=True)
        (self.tmp / "jarvis-apps/apps/node_modules").mkdir(parents=True)
        self.assertEqual([a for a, _ in paths.list_apps()], ["visible"])

    def test_list_apps_primer_root_gana(self):
        """Dos raíces con una app homónima: la primera gana y no se duplica."""
        a = self.mkproject("ra/dup")
        self.mkproject("rb/dup")
        os.environ["JARVIS_MAP_APPS_DIR"] = os.pathsep.join(
            [str(self.tmp / "ra"), str(self.tmp / "rb")]
        )
        apps = paths.list_apps()
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0][1], a)


class TestClaudeHome(_HomeFixture):

    def test_default(self):
        self.assertEqual(paths.claude_home(), self.tmp / ".claude")

    def test_respeta_env(self):
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.tmp / "otro-claude")
        self.assertEqual(paths.claude_home(), self.tmp / "otro-claude")

    def test_open_roots_incluye_dirs_con_claude_md(self):
        (self.tmp / ".claude").mkdir()
        agente = self.tmp / "agente-x"
        agente.mkdir()
        (agente / "CLAUDE.md").write_text("# agente-x", encoding="utf-8")
        (self.tmp / "sin-claude-md").mkdir()
        roots = paths.allowed_open_roots()
        self.assertIn(agente, roots)
        self.assertNotIn(self.tmp / "sin-claude-md", roots)


if __name__ == "__main__":
    unittest.main()
