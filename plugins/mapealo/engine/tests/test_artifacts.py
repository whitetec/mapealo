import unittest
from tests._fx import write_app
from analyzer.artifacts import detect_artifacts, artifact_type


class TestArtifactType(unittest.TestCase):
    def test_image(self):
        self.assertEqual(artifact_type("foo.png"), "image")
        self.assertEqual(artifact_type("a/b/c.JPEG"), "image")

    def test_data_and_db(self):
        self.assertEqual(artifact_type("out.json"), "data")
        self.assertEqual(artifact_type("data.sqlite3"), "database")

    def test_directory(self):
        self.assertEqual(artifact_type("path/to/dir/"), "directory")
        self.assertEqual(artifact_type("noext"), "directory")


class TestDetectArtifacts(unittest.TestCase):
    def _detect(self, src: str):
        d = write_app({"m.py": src})
        return detect_artifacts(d / "m.py")

    def test_open_write_and_read(self):
        arts = self._detect(
            "def f():\n"
            "    open('out/a.txt', 'w').write('x')\n"
            "    open('in/b.csv', 'r').read()\n"
        )
        ops = {(a["op"], a["path_hint"]) for a in arts}
        self.assertIn(("write", "out/a.txt"), ops)
        self.assertIn(("read",  "in/b.csv"),  ops)

    def test_imwrite_with_str_wrapper(self):
        arts = self._detect(
            "def f(out_web):\n"
            "    imwrite(str(out_web), img)\n"
            "    out_web = 'images/out.png'\n"
        )
        # local hint resuelve out_web → 'images/out.png'
        self.assertIn(("write", "images/out.png"),
                      {(a["op"], a["path_hint"]) for a in arts})

    def test_pathlib_write_text_with_local_assign(self):
        arts = self._detect(
            "def f(d):\n"
            "    json_path = d / 'x.json'\n"
            "    json_path.write_text('{}')\n"
        )
        self.assertIn(("write", "x.json"),
                      {(a["op"], a["path_hint"]) for a in arts})

    def test_constant_with_output_keyword(self):
        arts = self._detect(
            "OUTPUT_DIR = 'build/out/'\n"
            "INPUT_FILE = 'src/in.txt'\n"
        )
        ops = {(a["op"], a["path_hint"]) for a in arts}
        self.assertIn(("write", "build/out/"), ops)
        self.assertIn(("read",  "src/in.txt"), ops)

    def test_makedirs(self):
        arts = self._detect("import os\nos.makedirs('logs/today')\n")
        self.assertIn(("write", "logs/today/"),
                      {(a["op"], a["path_hint"]) for a in arts})

    def test_fstring_prefix_captured(self):
        arts = self._detect(
            "def f(name):\n"
            "    open(f'out/{name}.json', 'w')\n"
        )
        # En f-strings con interpolación, capturamos el prefijo estático
        # como pista del directorio (no la extensión).
        hints = {a["path_hint"] for a in arts}
        self.assertIn("out/", hints)

    def test_syntax_error_returns_empty(self):
        arts = self._detect("def f(:\n  pass")
        self.assertEqual(arts, [])


if __name__ == "__main__":
    unittest.main()
