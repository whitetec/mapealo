"""End-to-end: generate_wp() sobre un fixture WP completo."""
import unittest
from tests._fx import write_app
from analyzer.wp import generate_wp


WP_CONFIG = "<?php\n// fake wp-config\n"

PLUGIN_MAIN = (
    "<?php\n"
    "/*\n"
    " * Plugin Name: Bookings\n"
    " * Version: 2.1\n"
    " * Description: Reservas online.\n"
    " */\n"
    "function bk_init() {\n"
    "    register_post_type('booking', array());\n"
    "    register_post_type('venue', array());\n"
    "    add_shortcode('booking_form', 'bk_render_form');\n"
    "}\n"
    "add_action('init', 'bk_init');\n"
)

THEME_CSS = (
    "/*\n"
    "Theme Name: Acme\n"
    "Version: 1.0\n"
    "*/\n"
)

CHILD_CSS = (
    "/*\n"
    "Theme Name: Acme Child\n"
    "Template: acme\n"
    "*/\n"
)


class TestWpEndToEnd(unittest.TestCase):
    def test_full_pipeline(self):
        d = write_app({
            "wp-config.php":                                           WP_CONFIG,
            "wp-content/plugins/bookings/bookings.php":                PLUGIN_MAIN,
            "wp-content/themes/acme/style.css":                        THEME_CSS,
            "wp-content/themes/acme-child/style.css":                  CHILD_CSS,
        })
        graph, detail, stack, n = generate_wp(d, depth="basico", app_display="Acme Site")

        self.assertEqual(stack, "wordpress")

        pillars = {p["id"] for p in graph["pillars"]}
        self.assertEqual(pillars, {"plugins", "theme", "contenido"})

        ids = {c["id"] for c in graph["children"]}
        self.assertIn("plugin:bookings",    ids)
        self.assertIn("theme:acme",         ids)
        self.assertIn("theme:acme-child",   ids)
        self.assertIn("cpt:booking",        ids)
        self.assertIn("cpt:venue",          ids)
        self.assertIn("shortcode:booking_form", ids)

        # Detail del plugin trae sections data-driven
        d_plugin = detail["plugin:bookings"]
        labels   = [s["label"] for s in d_plugin["sections"]]
        self.assertIn("Información", labels)
        self.assertIn("CPTs",        labels)
        self.assertIn("Shortcodes",  labels)

        # Versión del plugin presente en Información (pair = [value, label_tooltip])
        info_items = next(s for s in d_plugin["sections"] if s["label"] == "Información")["items"]
        # Reverse dict: tooltip → value
        by_label = {label: value for value, label in info_items}
        self.assertEqual(by_label.get("Version"), "2.1")

        # Modo profundo: dep edges contenido → plugin/theme
        graph2, _, _, _ = generate_wp(d, depth="profundo", app_display="Acme Site")
        self.assertTrue(any(e["source"] == "cpt:booking" and e["target"] == "plugin:bookings"
                            for e in graph2["deps"]))


if __name__ == "__main__":
    unittest.main()
