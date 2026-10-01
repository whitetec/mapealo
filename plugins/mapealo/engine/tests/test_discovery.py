"""Tests de la autodetección del ecosistema de agentes — discovery.py.

Cada test arma un HOME falso con el layout de Claude Code y verifica que el
detector lo encuentre sin ninguna configuración. Es el escenario de una
máquina ajena: no hay fichas ni `jarvis-map.json` que le digan dónde mirar.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from _fx import write_app  # noqa: F401  (asegura jarvis-map en sys.path)

from analyzer.jarvis_agents import discovery, _generate_auto
from analyzer.jarvis_agents.discovery import (
    P_AGENT, P_COMMAND, P_HOOK, P_MCP, P_PLUGIN, P_SKILL,
)


def _w(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class _EcoFixture(unittest.TestCase):

    def setUp(self):
        self.tmp   = Path(tempfile.mkdtemp(prefix="jmap-eco-"))
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
        self.cc = self.tmp / ".claude"

    def tearDown(self):
        for k, v in self._envs.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def ids(self, comps, pillar=None):
        return sorted(c["id"] for c in comps if pillar is None or c["pillar"] == pillar)


class TestFrontmatter(_EcoFixture):

    def test_parsea_claves_planas_y_cuerpo(self):
        f = _w(self.cc / "agents/x.md",
               '---\nname: revisor\ndescription: "Revisa diffs"\nmodel: sonnet\n---\n\n# Revisor\n\ncuerpo')
        fm, body = discovery.read_frontmatter(f)
        self.assertEqual(fm["name"], "revisor")
        self.assertEqual(fm["description"], "Revisa diffs")
        self.assertEqual(fm["model"], "sonnet")
        self.assertIn("cuerpo", body)

    def test_archivo_sin_frontmatter(self):
        f = _w(self.cc / "commands/x.md", "# Solo título\n\ntexto")
        fm, body = discovery.read_frontmatter(f)
        self.assertEqual(fm, {})
        self.assertIn("Solo título", body)

    def test_frontmatter_sin_cerrar_no_se_come_el_archivo(self):
        f = _w(self.cc / "agents/y.md", "---\nname: trunco\nsin cierre\n")
        fm, _ = discovery.read_frontmatter(f)
        self.assertEqual(fm.get("name"), "trunco")

    def test_archivo_ilegible_no_rompe(self):
        fm, body = discovery.read_frontmatter(self.tmp / "no-existe.md")
        self.assertEqual((fm, body), ({}, ""))


class TestScanners(_EcoFixture):

    def test_subagentes(self):
        _w(self.cc / "agents/revisor.md",
           "---\nname: revisor\ndescription: Revisa código\ntools: Read, Grep\n---\n")
        _w(self.cc / "agents/anidado/otro.md", "---\nname: otro\n---\n")
        comps = discovery.scan_agents_md(self.cc, "usuario")
        self.assertEqual(self.ids(comps), ["otro", "revisor"])
        rev = next(c for c in comps if c["id"] == "revisor")
        self.assertEqual(rev["pillar"], P_AGENT)
        self.assertEqual(rev["desc"], "Revisa código")
        self.assertIn(["Read, Grep", "Tools"], rev["items"])

    def test_agents_usa_el_stem_si_no_hay_name(self):
        _w(self.cc / "agents/sin-name.md", "# Título\n")
        comps = discovery.scan_agents_md(self.cc, "usuario")
        self.assertEqual(self.ids(comps), ["sin-name"])
        self.assertEqual(comps[0]["desc"], "Título")

    def test_skills_incluye_las_sincronizadas(self):
        _w(self.cc / "skills/propia/SKILL.md", "---\nname: propia\ndescription: Mía\n---\n")
        _w(self.cc / "skills/synced/bucket-uuid/ajena/SKILL.md",
           "---\nname: ajena\ndescription: Sincronizada\n---\n")
        comps = discovery.scan_skills(self.cc, "usuario")
        self.assertEqual(self.ids(comps), ["ajena", "propia"])
        ajena = next(c for c in comps if c["id"] == "ajena")
        self.assertIn("sincronizada", ajena["tags"])
        propia = next(c for c in comps if c["id"] == "propia")
        self.assertNotIn("sincronizada", propia["tags"])

    def test_comandos_con_namespace(self):
        _w(self.cc / "commands/deploy.md", "---\ndescription: Despliega\n---\n")
        _w(self.cc / "commands/db/migrate.md", "# Migra\n")
        comps = discovery.scan_commands(self.cc, "usuario")
        self.assertEqual(self.ids(comps), ["/db:migrate", "/deploy"])
        self.assertTrue(all(c["pillar"] == P_COMMAND for c in comps))

    def test_plugins_y_sus_skills(self):
        inst = self.cc / "plugins/cache/mercado/mi-plugin/1.0"
        _w(inst / ".claude-plugin/plugin.json",
           json.dumps({"name": "mi-plugin", "description": "Hace cosas"}))
        _w(inst / "skills/incluida/SKILL.md",
           "---\nname: incluida\ndescription: Viene en el plugin\n---\n")
        _w(self.cc / "plugins/installed_plugins.json", json.dumps({
            "version": 2,
            "plugins": {"mi-plugin@mercado": [
                {"scope": "user", "installPath": str(inst), "version": "1.0"}
            ]},
        }))
        comps = discovery.scan_plugins(self.cc)
        self.assertEqual(self.ids(comps, P_PLUGIN), ["mi-plugin"])
        self.assertEqual(self.ids(comps, P_SKILL), ["incluida"])
        plugin = next(c for c in comps if c["pillar"] == P_PLUGIN)
        self.assertEqual(plugin["desc"], "Hace cosas")
        self.assertIn(["mercado", "Marketplace"], plugin["items"])
        skill = next(c for c in comps if c["pillar"] == P_SKILL)
        self.assertEqual(skill["scope"], "plugin:mi-plugin")

    def test_registro_de_plugins_corrupto_no_rompe(self):
        _w(self.cc / "plugins/installed_plugins.json", "{roto")
        self.assertEqual(discovery.scan_plugins(self.cc), [])

    def test_mcp_usuario_y_proyecto(self):
        _w(self.tmp / ".claude.json", json.dumps({"mcpServers": {
            "figma": {"type": "http", "url": "https://x/mcp"},
        }}))
        proy = self.tmp / "proyectos/app-a"
        _w(proy / ".mcp.json", json.dumps({"mcpServers": {
            "local-wp": {"command": "npx", "args": ["wp-mcp"]},
        }}))
        comps = discovery.scan_mcp(self.cc, [proy])
        self.assertEqual(self.ids(comps), ["figma", "local-wp"])
        figma = next(c for c in comps if c["id"] == "figma")
        self.assertEqual(figma["scope"], "usuario")
        self.assertIn("http", figma["tags"])
        wp = next(c for c in comps if c["id"] == "local-wp")
        self.assertEqual(wp["scope"], "proyecto:app-a")
        self.assertIn("stdio", wp["tags"])

    def test_hooks_uno_por_evento(self):
        _w(self.cc / "settings.json", json.dumps({"hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": "x"}]}],
            "PreToolUse":   [{"matcher": "Bash"}, {"matcher": "Edit"}],
        }}))
        comps = discovery.scan_hooks(self.cc)
        self.assertEqual(self.ids(comps), ["hook:PreToolUse", "hook:SessionStart"])
        pre = next(c for c in comps if c["id"] == "hook:PreToolUse")
        self.assertEqual(pre["pillar"], P_HOOK)
        self.assertIn(["2", "Matchers"], pre["items"])

    def test_dirs_con_claude_md_son_agentes(self):
        _w(self.tmp / "agente-x/CLAUDE.md", "# Agente X\n\ninstrucciones")
        (self.tmp / "sin-nada").mkdir()
        comps = discovery.scan_claude_md_dirs(
            [self.tmp / "agente-x", self.tmp / "sin-nada"]
        )
        self.assertEqual(self.ids(comps), ["agente-x"])
        self.assertEqual(comps[0]["desc"], "Agente X")
        self.assertEqual(comps[0]["pillar"], P_AGENT)

    def test_proyecto_anidado_con_claude_md_tambien_es_agente(self):
        """Los proyectos del operador pueden estar bajo `~/src`, no en el home:
        un `CLAUDE.md` ahí cuenta igual."""
        proy = self.tmp / "src/api-gateway"
        _w(proy / "requirements.txt", "")
        _w(proy / "CLAUDE.md", "# api-gateway")
        comps = discovery.detect_ecosystem()["components"]
        self.assertIn("api-gateway", self.ids(comps, P_AGENT))


class TestComposicion(_EcoFixture):

    def _eco_completo(self):
        _w(self.cc / "agents/revisor.md", "---\nname: revisor\ndescription: Revisa\n---\n")
        _w(self.cc / "skills/mapear/SKILL.md", "---\nname: mapear\ndescription: Mapea\n---\n")
        _w(self.cc / "commands/deploy.md", "---\ndescription: Despliega\n---\n")
        _w(self.cc / "settings.json", json.dumps({"hooks": {"SessionStart": [{}]}}))
        _w(self.tmp / ".claude.json", json.dumps({"mcpServers": {"figma": {"url": "u"}}}))
        _w(self.tmp / "agente-x/CLAUDE.md", "# Agente X")
        proy = self.tmp / "proyectos/app-a"
        _w(proy / "requirements.txt", "")
        _w(proy / ".claude/agents/local.md", "---\nname: local\ndescription: De proyecto\n---\n")

    def test_detecta_todas_las_fuentes(self):
        self._eco_completo()
        eco   = discovery.detect_ecosystem()
        comps = eco["components"]
        self.assertEqual(sorted(eco["sources"]["found_by_pillar"]),
                         [P_AGENT, P_COMMAND, P_HOOK, P_MCP, P_SKILL])
        self.assertIn("revisor", self.ids(comps, P_AGENT))
        self.assertIn("local",   self.ids(comps, P_AGENT))
        self.assertIn("agente-x", self.ids(comps, P_AGENT))
        self.assertIn("mapear",  self.ids(comps, P_SKILL))
        self.assertIn("/deploy", self.ids(comps, P_COMMAND))
        self.assertIn("figma",   self.ids(comps, P_MCP))
        self.assertEqual(eco["sources"]["claude_home"], str(self.cc))

    def test_home_vacio_no_rompe(self):
        eco = discovery.detect_ecosystem()
        self.assertEqual(eco["components"], [])

    def test_dedup_conserva_la_fuente_mas_informativa(self):
        """El mismo agente visto como dir con CLAUDE.md y como subagente con
        descripción: un solo nodo, y gana el que trae descripción."""
        _w(self.tmp / "duplicado/CLAUDE.md", "")
        _w(self.cc / "agents/duplicado.md",
           "---\nname: duplicado\ndescription: La buena\n---\n")
        comps = discovery.detect_ecosystem()["components"]
        dups  = [c for c in comps if c["id"] == "duplicado"]
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["desc"], "La buena")

    def test_ids_unicos_al_chocar_pilares(self):
        """Una skill y un plugin homónimos son dos nodos: el grafo se indexa
        por id, así que la colisión tiene que romperse."""
        inst = self.cc / "plugins/cache/m/gemelo/1.0"
        _w(inst / ".claude-plugin/plugin.json", json.dumps({"name": "gemelo"}))
        _w(self.cc / "plugins/installed_plugins.json", json.dumps({
            "plugins": {"gemelo@m": [{"scope": "user", "installPath": str(inst)}]},
        }))
        _w(self.cc / "skills/gemelo/SKILL.md", "---\nname: gemelo\n---\n")
        _, detail, _, n = _generate_auto("basico", "Eco", [])
        self.assertEqual(n, 2)
        self.assertEqual(sorted(detail), ["gemelo (plugin)", "gemelo (skill)"])


class TestPipelineAuto(_EcoFixture):

    def test_grafo_con_pilares_por_fuente(self):
        _w(self.cc / "agents/revisor.md", "---\nname: revisor\ndescription: Revisa\n---\n")
        _w(self.cc / "skills/mapear/SKILL.md", "---\nname: mapear\n---\n")
        graph, detail, stack, n = _generate_auto("basico", "Mi ecosistema", [])
        self.assertEqual(stack, "claude-code-agents")
        self.assertEqual(n, 2)
        self.assertEqual([p["id"] for p in graph["pillars"]], [P_AGENT, P_SKILL])
        self.assertEqual(graph["app_display"], "Mi ecosistema")
        self.assertEqual(graph["groups"][0]["label"], "Mi ecosistema")
        self.assertIn("discovery", graph)
        self.assertEqual(sorted(detail), ["mapear", "revisor"])
        self.assertEqual(graph["deps"], [])  # basico no infiere aristas

    def test_deps_por_pertenencia_a_plugin(self):
        inst = self.cc / "plugins/cache/m/pack/1.0"
        _w(inst / ".claude-plugin/plugin.json", json.dumps({"name": "pack"}))
        _w(inst / "skills/incluida/SKILL.md", "---\nname: incluida\n---\n")
        _w(self.cc / "plugins/installed_plugins.json", json.dumps({
            "plugins": {"pack@m": [{"scope": "user", "installPath": str(inst)}]},
        }))
        graph, _, _, _ = _generate_auto("profundo", "Eco", [])
        self.assertIn({"source": "incluida", "target": "pack"}, graph["deps"])

    def test_deps_por_referencia_cruzada(self):
        _w(self.cc / "agents/revisor.md", "---\nname: revisor\n---\n")
        _w(self.cc / "skills/mapear/SKILL.md",
           "---\nname: mapear\n---\n\nDelegá en revisor cuando haga falta.\n")
        graph, _, _, _ = _generate_auto("profundo", "Eco", [])
        self.assertIn({"source": "mapear", "target": "revisor"}, graph["deps"])

    def test_sin_autoreferencia(self):
        _w(self.cc / "skills/mapear/SKILL.md",
           "---\nname: mapear\n---\n\nmapear mapear mapear\n")
        graph, _, _, _ = _generate_auto("profundo", "Eco", [])
        self.assertEqual(graph["deps"], [])

    def test_las_fichas_enriquecen_sin_reemplazar(self):
        """En modo auto, una ficha del operador suma Tipo/Capability al agente
        detectado: es taxonomía que ninguna convención estándar expresa."""
        _w(self.tmp / "jarvis-dev/CLAUDE.md", "# jarvis-dev")
        ficha = {"slug": "jarvis-dev", "tipo": "T", "especialidad": "WordPress",
                 "capability": "6/6", "autonomy": "L2"}
        _, detail, _, n = _generate_auto("basico", "Eco", [ficha])
        self.assertEqual(n, 1)
        items = detail["jarvis-dev"]["sections"][0]["items"]
        self.assertIn(["T", "Tipo"], items)
        self.assertIn(["6/6", "Capability"], items)
        self.assertIn("ficha", detail["jarvis-dev"]["tags"])

    def test_ficha_sin_agente_detectado_no_inventa_nodo(self):
        _w(self.cc / "skills/mapear/SKILL.md", "---\nname: mapear\n---\n")
        ficha = {"slug": "agente-fantasma", "tipo": "T"}
        _, detail, _, n = _generate_auto("basico", "Eco", [ficha])
        self.assertEqual(n, 1)
        self.assertNotIn("agente-fantasma", detail)


if __name__ == "__main__":
    unittest.main()
