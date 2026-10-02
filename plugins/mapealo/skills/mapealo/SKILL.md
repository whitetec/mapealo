---
name: mapealo
description: Genera o actualiza el mapa de arquitectura de un proyecto, o del ecosistema de agentes de esta máquina, y lo abre en un visualizador local. Usalo cuando el usuario pida "mapealo", "mapeá <proyecto>", "generá el mapa de X", "actualizá el mapa", "mapear la arquitectura", "quiero ver cómo está armado esto", "mostrame el mapa de mis agentes", "qué skills/plugins/MCP tengo instalados" o "/mapealo". Acepta el nombre del proyecto, su ruta, o la palabra "agentes". También se activa si el usuario pide abrir el visualizador y el proyecto todavía no tiene mapa.
---

# mapealo - mapa de arquitectura

Analiza un proyecto y genera los archivos `.mapealo/` que consume el
visualizador. Mapea dos cosas distintas:

- **Un proyecto**: Python (Flask / FastAPI), Next.js o WordPress.
- **El ecosistema de agentes de la máquina**: agentes, skills, comandos,
  plugins, servidores MCP y hooks. Se autodetecta, no hay que configurarlo.

## Paso 0 - ubicar el motor

El motor viaja dentro de este plugin. Resolvé su ruta una vez y reusá
`$ENGINE` en el resto de los comandos de la misma invocación de Bash:

```bash
ENGINE="${CLAUDE_PLUGIN_ROOT:-}/engine"
[ -f "$ENGINE/mapealo.py" ] || ENGINE=$(ls -d ~/.claude/plugins/cache/*/mapealo/*/engine 2>/dev/null | head -1)
[ -f "$ENGINE/mapealo.py" ] || ENGINE=$(ls -d ~/.claude/plugins/marketplaces/*/plugins/mapealo/engine 2>/dev/null | head -1)
echo "$ENGINE"
```

Si ninguna de las tres resuelve, el plugin está mal instalado: decíselo al
usuario y pará. No busques el script por el filesystem entero.

**Dependencias:** `fastapi` y `uvicorn`, solo para el visualizador. Generar el
mapa no necesita nada más que Python 3.10+. Si al abrir el visualizador falta
alguna, instalalas con `python3 -m pip install -r "$ENGINE/requirements.txt"`
y avisá que lo hiciste.

## Paso 1 - resolver qué mapear

Leé el argumento del usuario:

| Lo que pidió | Qué pasarle al script |
|---|---|
| un nombre (`anubis`) | el nombre tal cual |
| una ruta (`~/dev/mi-app`, `.`) | la ruta tal cual |
| "mis agentes", "el ecosistema", nada claro pero habla de agentes/skills/plugins | `agentes --kind agents` |
| nada | ver abajo |

Si no pasó argumento, mostrale qué hay disponible antes de preguntar:

```bash
python3 "$ENGINE/mapealo.py" --roots
```

Devuelve JSON con las raíces detectadas y los proyectos visibles. Presentale
esa lista y que elija. Si `roots` viene vacío, no hay ninguna raíz reconocible:
pedile la ruta del proyecto, o que defina `MAPEALO_APPS_DIR`.

## Paso 2 - verificar estado

```bash
python3 "$ENGINE/mapealo.py" <objetivo> --status
```

El resultado es JSON:

| Campo | Qué significa |
|---|---|
| `"mapped": false` | No existe mapa → **Primer mapeo** |
| `"mapped": true, "stale": false` | Actualizado → abrir el visualizador |
| `"mapped": true, "stale": true` | Hay cambios → **Actualización** |
| `"error"` con `roots` y `hint` | No se encontró el proyecto: mostrale el `hint` |

## Flujo A - primer mapeo

Preguntale la profundidad:

> "No existe mapa para `<objetivo>`. ¿Qué profundidad querés?
> **[1] Básico** - estructura, funciones, modelos, rutas (~10s)
> **[2] Profundo** - todo lo anterior + call graph, relaciones entre modelos,
> imports, variables de entorno, dependencias externas, tests (~1-2 min)"

```bash
python3 "$ENGINE/mapealo.py" <objetivo> --depth basico
python3 "$ENGINE/mapealo.py" <objetivo> --depth profundo
```

Para el ecosistema de agentes, `profundo` agrega las aristas entre componentes
(qué skill viene de qué plugin, qué componente nombra a qué otro). Vale la pena
y tarda lo mismo: ofrecé `profundo` directamente en ese caso.

Si el resultado tiene `"ok": true`, abrí el visualizador sin volver a preguntar
y confirmá en una línea:

> "Mapa generado: X componentes, stack `<stack>`. Abriendo el visualizador..."

## Flujo B - actualización

> "El mapa de `<objetivo>` tiene cambios (`<last_changelog_entry>` → `<latest_changelog>`).
> **[1] Actualizar** - misma profundidad
> **[2] Upgrade a profundo** - agrega las capas avanzadas
> **[3] Cancelar**"

```bash
python3 "$ENGINE/mapealo.py" <objetivo> --depth <actual>  --force
python3 "$ENGINE/mapealo.py" <objetivo> --depth profundo  --force
```

## Flujo C - sin cambios

> "El mapa de `<objetivo>` está actualizado. Abriendo el visualizador..."

## Abrir el visualizador

```bash
curl -s --max-time 2 http://localhost:17433/api/apps > /dev/null 2>&1 || \
  nohup python3 -m uvicorn app:app --host 127.0.0.1 --port 17433 \
    --app-dir "$ENGINE" > /tmp/mapealo.log 2>&1 &
sleep 2
xdg-open "http://localhost:17433/?app=<objetivo>" 2>/dev/null || \
  open      "http://localhost:17433/?app=<objetivo>" 2>/dev/null || \
  echo "Abrí http://localhost:17433/?app=<objetivo>"
```

Si el navegador no abre solo, pasale la URL al usuario en texto.

## Interpretar el resultado

| Síntoma | Qué significa |
|---|---|
| `modules: 0` | No encontró archivos del stack. Verificá que la ruta sea la del proyecto y no la de su directorio padre. |
| `stack: unknown` | Stack no reconocido. Soportados: Python (Flask / FastAPI), Next.js, WordPress. |
| `stack: claude-code-agents` | Mapeó el ecosistema de agentes. El campo `discovery` del grafo dice de dónde salió cada cosa. |
| `modules` muy por debajo de lo esperado | Puede estar mapeando un subdirectorio. Probá pasando la ruta absoluta. |

## Qué no hacer

- **No editar a mano** los archivos de `.mapealo/` (`graph.json`,
  `detail.json`, `meta.json`). Son artefactos generados: si algo sale mal, se
  corrige el analizador y se regenera, no el output.
- `.mapealo/` es del visualizador, no documentación del proyecto. Si el
  proyecto está en git, conviene agregarlo al `.gitignore`.
- No asumas rutas del autor del plugin: todo se resuelve con `$ENGINE` y con
  `--roots`.

## Dónde busca los proyectos

Por orden de precedencia:

1. `MAPEALO_APPS_DIR` (lista separada por `:`)
2. `~/.config/mapealo/config.json` → `{"apps_dirs": ["..."]}`
3. autodetección: `~/proyectos`, `~/projects`, `~/dev`, `~/src`, `~/code`,
   `~/repos`, `~/work`, `~/workspace` y variantes
4. el workspace propio del tool (`~/.local/share/mapealo/apps`), donde vive
   el stub del ecosistema de agentes

Una ruta explícita siempre gana sobre todo esto.
