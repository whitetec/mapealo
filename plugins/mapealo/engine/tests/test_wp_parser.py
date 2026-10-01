import unittest
from tests._fx import write_app
from analyzer.wp.parser import parse_php_file, parse_php_components


class TestParsePhpFile(unittest.TestCase):
    def _parse(self, src: str):
        d = write_app({"x.php": src})
        return parse_php_file(d / "x.php")

    def test_register_post_type_literal(self):
        r = self._parse("<?php register_post_type('book', array());")
        self.assertEqual(r["cpts"], ["book"])

    def test_register_post_type_double_quote(self):
        r = self._parse('<?php register_post_type("movie", $args);')
        self.assertEqual(r["cpts"], ["movie"])

    def test_add_shortcode_literal(self):
        r = self._parse("<?php add_shortcode('hello', 'render_hello');")
        self.assertEqual(r["shortcodes"], ["hello"])

    def test_dedup_and_sort(self):
        src = ("<?php\n"
               "register_post_type('book', []);\n"
               "register_post_type('movie', []);\n"
               "register_post_type('book', []);\n")
        r = self._parse(src)
        self.assertEqual(r["cpts"], ["book", "movie"])

    def test_var_arg_ignored_silently(self):
        r = self._parse("<?php register_post_type($slug, []);")
        self.assertEqual(r["cpts"], [])

    def test_constant_arg_ignored(self):
        r = self._parse("<?php register_post_type(MY_CPT, []);")
        self.assertEqual(r["cpts"], [])

    def test_concat_arg_ignored(self):
        r = self._parse("<?php register_post_type('prefix_' . $name, []);")
        self.assertEqual(r["cpts"], [])

    def test_method_call_with_same_name_not_matched(self):
        # $obj->register_post_type('x') no debe matchear (el lookbehind \w protege)
        r = self._parse("<?php $obj->register_post_type('x');")
        self.assertEqual(r["cpts"], [])

    def test_unrelated_function_ignored(self):
        r = self._parse("<?php some_other_func('book');")
        self.assertEqual(r["cpts"], [])
        self.assertEqual(r["shortcodes"], [])


class TestParsePhpComponents(unittest.TestCase):
    def test_aggregates_across_files_skips_vendor(self):
        d = write_app({
            "main.php":              "<?php register_post_type('book', []);",
            "inc/cpt.php":           "<?php register_post_type('movie', []);",
            "inc/short.php":         "<?php add_shortcode('greet', 'fn');",
            "vendor/lib/legacy.php": "<?php register_post_type('SHOULD_SKIP', []);",
        })
        r = parse_php_components(d)
        self.assertEqual(r["cpts"],       ["book", "movie"])
        self.assertEqual(r["shortcodes"], ["greet"])


if __name__ == "__main__":
    unittest.main()
