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


class TestNombresLegacy(_HomeFixture):
    """El motor se llamaba `jarvis-map` antes de publicarse como `mapealo`.
    Lo que el usuario ve usa el nombre nuevo; lo viejo se sigue leyendo para no
    invalidar los mapas y configs ya generados."""

    def test_out_dir_nuevo_por_defecto(self):
        d = self.mkproject("jarvis-apps/apps/limpia")
        self.assertEqual(paths.out_dir(d).name, ".mapealo")

    def test_out_dir_conserva_el_viejo_si_existe(self):
        d = self.mkproject("jarvis-apps/apps/vieja")
        (d / ".jarvis-map").mkdir()
        self.assertEqual(paths.out_dir(d), d / ".jarvis-map")

    def test_out_dir_prefiere_el_nuevo_si_estan_los_dos(self):
        d = self.mkproject("jarvis-apps/apps/ambas")
        (d / ".jarvis-map").mkdir()
        (d / ".mapealo").mkdir()
        self.assertEqual(paths.out_dir(d), d / ".mapealo")

    def test_config_de_proyecto_acepta_los_dos_nombres(self):
        d = self.mkproject("jarvis-apps/apps/conf")
        self.assertIsNone(paths.project_config(d))
        (d / "jarvis-map.json").write_text("{}", encoding="utf-8")
        self.assertEqual(paths.project_config(d).name, "jarvis-map.json")
        (d / "mapealo.json").write_text("{}", encoding="utf-8")
        self.assertEqual(paths.project_config(d).name, "mapealo.json")

    def test_env_var_vieja_sigue_valiendo(self):
        externa = self.tmp / "por-env-vieja"
        externa.mkdir()
        os.environ["JARVIS_MAP_APPS_DIR"] = str(externa)
        self.assertIn(externa, paths.apps_roots())

    def test_env_var_nueva_gana_sobre_la_vieja(self):
        nueva, vieja = self.tmp / "nueva", self.tmp / "vieja"
        nueva.mkdir(); vieja.mkdir()
        os.environ["MAPEALO_APPS_DIR"]     = str(nueva)
        os.environ["JARVIS_MAP_APPS_DIR"]  = str(vieja)
        try:
            self.assertEqual(paths.apps_roots()[0], nueva)
            self.assertNotIn(vieja, paths.apps_roots())
        finally:
            os.environ.pop("MAPEALO_APPS_DIR", None)

    def test_user_config_cae_al_viejo_si_es_el_que_esta(self):
        viejo = self.tmp / ".config/jarvis-map/config.json"
        viejo.parent.mkdir(parents=True)
        viejo.write_text("{}", encoding="utf-8")
        self.assertEqual(paths.user_config(), viejo)

    def test_workspace_cae_al_viejo_si_es_el_que_esta(self):
        viejo = self.tmp / ".local/share/jarvis-map/apps"
        viejo.mkdir(parents=True)
        self.assertEqual(paths.workspace_root(), viejo)

    def test_workspace_nuevo_por_defecto(self):
        self.assertEqual(paths.workspace_root().parent.name, "mapealo")


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
