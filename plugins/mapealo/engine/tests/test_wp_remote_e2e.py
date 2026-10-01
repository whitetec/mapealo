"""End-to-end del pipeline wordpress-remote, mockeando subprocess."""
import json
import unittest
from unittest.mock import patch

from tests._fx import write_app
from analyzer import detect_kind, KIND_WORDPRESS_REMOTE
from analyzer.wp_remote import generate_wp_remote


JARVIS_MAP_JSON = {
    "kind": "wordpress-remote",
    "ssh": {
        "host": "vps.example.com", "user": "deploy", "key": "~/.ssh/key",
        "wp_path": "/home/x/site/",
    },
    "local_php_dirs": ["mu-plugins"],
}

LOCAL_MU_PLUGIN = (
    "<?php\n"
    "register_post_type('local_only_cpt', []);\n"
    "add_shortcode('site_widget', 'render');\n"
)


def _wp_responses():
    """Mapa de comando WP-CLI → respuesta canned."""
    return {
        "plugin": [
            {"name": "elementor",   "title": "Elementor",   "status": "active",   "version": "3.21", "update": "none"},
            {"name": "tour",        "title": "Tours API",   "status": "must-use", "version": "1.0",  "update": "none"},
            {"name": "akismet",     "title": "Akismet",     "status": "inactive", "version": "5.3",  "update": "available"},
        ],
        "theme": [
            {"name": "hello-elementor", "title": "Hello",       "status": "active", "version": "3", "template": ""},
            {"name": "hello-child",     "title": "Hello Child", "status": "parent", "version": "1", "template": "hello-elementor"},
        ],
        "post-type": [
            {"name": "post", "label": "Posts", "public": "1", "hierarchical": ""},
            {"name": "tour", "label": "Tours", "public": "1", "hierarchical": ""},
            {"name": "salida", "label": "Salidas", "public": "", "hierarchical": ""},
        ],
        "taxonomy": [
            {"name": "category", "label": "Categories", "object_type": "post",        "hierarchical": "1"},
            {"name": "destino",  "label": "Destinos",   "object_type": "tour",        "hierarchical": "1"},
        ],
    }


def _mock_run_wp_cli(cfg, wp_args, **kwargs):
    """Reemplazo de run_wp_cli — devuelve respuestas según el primer arg."""
    return _wp_responses()[wp_args[0]]


class TestGenerateWpRemote(unittest.TestCase):
    def setUp(self):
        self.app_dir = write_app({
            "jarvis-map.json": json.dumps(JARVIS_MAP_JSON),
            "mu-plugins/site-api.php": LOCAL_MU_PLUGIN,
        })

    def test_detect_kind_uses_config(self):
        self.assertEqual(detect_kind(self.app_dir), KIND_WORDPRESS_REMOTE)

    @patch("analyzer.wp_remote.inventory.run_wp_cli", side_effect=_mock_run_wp_cli)
    def test_pipeline_combines_remote_and_local(self, _):
        graph, detail, stack, n = generate_wp_remote(
            self.app_dir, depth="profundo", app_display="Acme"
        )
        self.assertEqual(stack, "wordpress-remote")

        ids = {c["id"] for c in graph["children"]}
        # Remoto
        self.assertIn("plugin:elementor",            ids)
        self.assertIn("plugin:tour",                 ids)
        self.assertIn("theme:hello-elementor",       ids)
        self.assertIn("cpt:tour",                    ids)
        self.assertIn("cpt:salida",                  ids)
        self.assertIn("tax:destino",                 ids)
        # Local-only desde mu-plugin parseado
        self.assertIn("cpt:local_only_cpt",          ids)
        self.assertIn("shortcode:site_widget",       ids)

        # Pillars usados
        pillars = {p["id"] for p in graph["pillars"]}
        self.assertEqual(pillars, {"theme", "plugins", "contenido"})

        # Detail: plugin elementor tiene Estado, Versión (pair = [value, label_tooltip])
        d_elem = detail["plugin:elementor"]
        info = next(s for s in d_elem["sections"] if s["label"] == "Información")
        by_label = {label: value for value, label in info["items"]}
        self.assertEqual(by_label.get("Estado"),  "active")
        self.assertEqual(by_label.get("Versión"), "3.21")

        # Update-available aparece como tag
        d_akismet = next(c for c in graph["children"] if c["id"] == "plugin:akismet")
        self.assertIn("update-available", d_akismet["tags"])

        # Profundo: cpt:tour → plugin:tour (slug coincide)
        deps = graph["deps"]
        self.assertTrue(any(e["source"] == "cpt:tour" and e["target"] == "plugin:tour" for e in deps))

    @patch("analyzer.wp_remote.inventory.run_wp_cli", side_effect=_mock_run_wp_cli)
    def test_basico_omits_dep_edges(self, _):
        graph, _, _, _ = generate_wp_remote(self.app_dir, depth="basico", app_display="Acme")
        self.assertEqual(graph["deps"], [])


if __name__ == "__main__":
    unittest.main()
