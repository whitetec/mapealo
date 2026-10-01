import unittest
from pathlib import Path

from tests._fx import write_app
from analyzer import detect_kind, KIND_NEXTJS
from analyzer.nextjs import generate_nextjs, _alias, encontrar_raiz

APP = {
    # El sitio en un subdirectorio, como whitetec-web, y un script .py suelto
    # que antes hacía que la app se detectara como Python.
    "scripts/og.py": "print('og')\n",
    "sitio/package.json": '{"dependencies": {"next": "^16.2.7", "react": "19"}}',
    "sitio/tsconfig.json": '{\n  // comentario\n  "compilerOptions": {"paths": {"@/*": ["./src/*"]},},\n}\n',
    "sitio/src/app/page.tsx": (
        'import { Nav } from "@/components/Nav";\n'
        'import { saludo } from "@/lib/texto";\n'
        'import "@/components/estilos.css";\n'
        "export default function Home() {\n  return <Nav />;\n}\n"
    ),
    "sitio/src/app/(marketing)/precios/page.tsx": "export default function Precios() { return null; }\n",
    "sitio/src/app/api/contacto/route.ts": (
        'import { enviar } from "../../../lib/texto";\n'
        "export async function POST(req: Request) {\n  return enviar();\n}\n"
        "export const GET = () => new Response('ok');\n"
    ),
    "sitio/src/components/Nav.tsx": (
        '"use client";\n'
        "// Menú principal del sitio\n"
        "export function Nav() {\n  return (\n    <nav>{[1].map((x) => (<a key={x}>{x}</a>))}</nav>\n  );\n}\n"
    ),
    "sitio/src/lib/texto.ts": (
        "export const TITULO = 'Hola';\n"
        "export const saludo = (n: string) => `hola ${n}`;\n"
        "export function enviar() { return null; }\n"
        "export type Opcion = { a: string };\n"
    ),
    "sitio/src/app/servicios/page.tsx": (
        'import { Nav } from "@/components/Nav";\n'
        "export default function Servicios() {\n"
        "  return (\n"
        "    <>\n"
        "      <Nav />\n"
        "      <main>\n"
        "        {/* QUÉ OFRECE ATALAYA */}\n"
        '        <section id="oferta">\n'
        "          <section><p>interna</p></section>\n"
        "        </section>\n"
        "        {/* Franja de valor */}\n"
        '        <section className="franja"><p>x</p></section>\n'
        "        {/* MÓDULOS en lista */}\n"
        "        {[1, 2].map((m) => (\n"
        "          <section key={m} id={String(m)}>\n"
        "            <p>{m}</p>\n"
        "          </section>\n"
        "        ))}\n"
        "      </main>\n"
        "    </>\n"
        "  );\n"
        "}\n"
    ),
    "sitio/src/lib/marca.ts": 'export const NOMBRE = "Conocer ATALAYA";\n',
    "sitio/src/lib/texto.d.ts": "export declare const x: number;\n",
    "sitio/node_modules/next/index.js": "module.exports = {};\n",
    "sitio/src/generated/prisma/client.ts": "export const cliente = {};\n",
    "sitio/prisma/schema.prisma": (
        "model Mensaje {\n  id Int @id\n  texto String\n  @@index([id])\n}\n"
    ),
}


class TestDeteccion(unittest.TestCase):
    def test_next_en_subdirectorio_gana_a_python(self):
        d = write_app(APP)
        self.assertEqual(encontrar_raiz(d), d / "sitio")
        self.assertEqual(detect_kind(d), KIND_NEXTJS)

    def test_alias_con_comentarios_y_comodin(self):
        # "@/*" no puede leerse como inicio de un comentario /* ... */
        d = write_app(APP)
        alias = _alias(d / "sitio")
        self.assertEqual(alias[0][0], "@/")
        self.assertTrue(str(alias[0][1]).endswith("sitio/src"))


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = write_app(APP)
        cls.graph, cls.detail, cls.stack, cls.n = generate_nextjs(cls.d, app_display="demo")
        cls.ids = {c["id"] for c in cls.graph["children"]}

    def test_excluye_generados_node_modules_y_dts(self):
        self.assertNotIn("generated/prisma/client", self.ids)
        self.assertFalse(any("node_modules" in i for i in self.ids))
        self.assertNotIn("lib/texto.d", self.ids)

    def test_ids_sin_src_y_rel_path_real(self):
        nav = next(c for c in self.graph["children"] if c["id"] == "components/Nav")
        self.assertEqual(nav["rel_path"], "sitio/src/components/Nav.tsx")
        self.assertIn("components", {g["label"] for g in self.graph["groups"]})
        self.assertNotIn("src", {g["label"] for g in self.graph["groups"]})

    def test_imports_por_alias_y_relativos(self):
        deps = {(e["source"], e["target"]) for e in self.graph["deps"]}
        self.assertIn(("app/page", "components/Nav"), deps)
        self.assertIn(("app/page", "lib/texto"), deps)
        self.assertIn(("app/api/contacto/route", "lib/texto"), deps)

    def test_exports(self):
        fns = [f[0] for f in self.detail["components/Nav"]["fn"]]
        self.assertEqual(fns, ["Nav()"])
        self.assertEqual(self.detail["components/Nav"]["fn"][0][1], "Menú principal del sitio")
        self.assertIn("cliente", self.detail["components/Nav"]["tags"])
        texto = self.detail["lib/texto"]
        self.assertIn("saludo(n: string)", [f[0] for f in texto["fn"]])
        self.assertIn("enviar()", [f[0] for f in texto["fn"]])
        self.assertIn("TITULO", [v[0] for v in texto["vars"]])
        self.assertIn(["Opcion", "tipo"], texto["vars"])

    def test_rutas_y_grupos_de_rutas(self):
        self.assertIn(["GET /", "página"], self.detail["app/page"]["routes"])
        # (marketing) es un grupo de rutas: no suma a la URL
        self.assertIn(["GET /precios", "página"], self.detail["app/(marketing)/precios/page"]["routes"])
        rutas = [r[0] for r in self.detail["app/api/contacto/route"]["routes"]]
        self.assertEqual(sorted(rutas), ["GET /api/contacto", "POST /api/contacto"])
        self.assertEqual(self.detail["app/api/contacto/route"]["fn"], [])

    def test_modelos_prisma(self):
        self.assertEqual(self.detail["prisma/schema.prisma"]["models"], [["Mensaje", "id, texto"]])

    def test_vista_secciones(self):
        s = self.detail["_views"]["secciones"]
        urls = {c["url"] for c in s["children"]}
        self.assertEqual(urls, {"/", "/precios", "/servicios", "/api/contacto"})
        self.assertTrue(all(c["rel_path"].startswith("sitio/src/") for c in s["children"]))


class TestDiseno(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = write_app(APP)
        _, detail, _, _ = generate_nextjs(cls.d, app_display="demo")
        cls.v = detail["_views"]["diseño"]

    def _bloques(self, url):
        return [c for c in self.v["children"] if c["group"] == f"pagina:{url}"]

    def test_bloques_en_orden_con_nombres_legibles(self):
        b = self._bloques("/servicios")
        # la sección anidada no cuenta como bloque; ATALAYA se respeta en mayúsculas
        self.assertEqual([c["label"] for c in b],
                         ["01 · Menú", "02 · Qué ofrece ATALAYA", "03 · Franja de valor", "04 · MÓDULOS en lista"])
        self.assertEqual([c["fn"] for c in b[:3]], ["Nav", "#oferta", "/* Franja de valor"])
        self.assertEqual(b[0]["rel_path"], "sitio/src/components/Nav.tsx")
        self.assertEqual(b[1]["rel_path"], "sitio/src/app/servicios/page.tsx")

    def test_rango_de_cada_bloque(self):
        import puente
        pagina = self.d / "sitio/src/app/servicios/page.tsx"
        self.assertEqual(puente._rango_de(pagina, {"name": "#oferta"}), (8, 10))
        self.assertEqual(puente._rango_de(pagina, {"name": "/* Franja de valor"}), (12, 12))
        self.assertEqual(puente._rango_de(pagina, {"name": "/* MÓDULOS en lista"}), (15, 17))


class TestRangoTs(unittest.TestCase):
    def test_declaracion_y_fin_balanceado(self):
        import puente
        d = write_app(APP)
        nav = d / "sitio/src/components/Nav.tsx"
        self.assertEqual(puente._rango_de(nav, {"name": "Nav()"}), (3, 7))
        texto = d / "sitio/src/lib/texto.ts"
        self.assertEqual(puente._rango_de(texto, {"name": "enviar"}), (3, 3))
        # la llave dentro del template literal está en un string y no cuenta
        self.assertEqual(puente._rango_de(texto, {"name": "saludo"}), (2, 2))


if __name__ == "__main__":
    unittest.main()
