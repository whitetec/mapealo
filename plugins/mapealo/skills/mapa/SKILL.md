---
name: mapa
description: Abre el visualizador interactivo de arquitectura en el navegador. Usalo cuando el usuario pida ver el mapa, la arquitectura, el grafo o el diagrama de un proyecto, con frases como "mostrame el mapa de X", "abrí el mapa", "quiero ver cómo está armado Y", "qué módulos tiene X" o "/mapa". Acepta el nombre o la ruta del proyecto como argumento opcional, y la palabra "agentes" para el ecosistema de agentes de la máquina. Si el proyecto todavía no tiene mapa generado, usá la skill `mapealo` primero.
---

# mapa - visualizador de arquitectura

Servidor local en el puerto 17433 que sirve un grafo interactivo. Los datos los
genera la skill `mapealo` y viven en `<proyecto>/.mapealo/`.

## Paso 0 - ubicar el motor

```bash
ENGINE="${CLAUDE_PLUGIN_ROOT:-}/engine"
[ -f "$ENGINE/app.py" ] || ENGINE=$(ls -d ~/.claude/plugins/cache/*/mapealo/*/engine 2>/dev/null | head -1)
[ -f "$ENGINE/app.py" ] || ENGINE=$(ls -d ~/.claude/plugins/marketplaces/*/plugins/mapealo/engine 2>/dev/null | head -1)
echo "$ENGINE"
```

Si ninguna resuelve, el plugin está mal instalado: decíselo al usuario y pará.

## Paso 1 - levantar el servidor si no corre

```bash
curl -s --max-time 2 http://localhost:17433/api/apps > /dev/null 2>&1 || \
  nohup python3 -m uvicorn app:app --host 127.0.0.1 --port 17433 \
    --app-dir "$ENGINE" > /tmp/mapealo.log 2>&1 &
sleep 2
```

Si falla por dependencias, instalalas y avisá:
`python3 -m pip install -r "$ENGINE/requirements.txt"`.

## Paso 2 - resolver el proyecto

Con argumento, pedí la lista y buscá la coincidencia:

```bash
curl -s "http://localhost:17433/api/apps"
```

Cada entrada trae `id`, `mapped`, `stale`, `depth` y `kind`.

- Una sola coincidencia por nombre parcial → usala.
- Varias → elegí la más cercana, o preguntá si siguen siendo ambiguas.
- Ninguna → abrí sin parámetro, que la UI muestra el selector.
- `mapped: false` → el proyecto no tiene mapa: usá la skill `mapealo`.

## Paso 3 - abrir el navegador

```bash
xdg-open "http://localhost:17433/?app=<id>" 2>/dev/null || \
  open      "http://localhost:17433/?app=<id>" 2>/dev/null || \
  echo "Abrí http://localhost:17433/?app=<id>"
```

Sin app resuelta, la misma URL sin `?app=`. Si el navegador no abre solo,
pasale la URL en texto.

## Paso 4 - confirmar

Una línea con qué se abrió. Si el mapa estaba desactualizado (`stale: true`),
decilo: la UI lo marca como DESACTUALIZADO y tiene un botón **Regenerar**, así
que no hace falta volver a la terminal.

## Notas

- El puerto 17433 es exclusivo de este visualizador.
- Log del servidor: `/tmp/mapealo.log`.
- El backend valida el `app_id` contra una allowlist: la superficie HTTP acepta
  ids, nunca rutas.
- Vistas disponibles según el proyecto: Estructura (por defecto), Secciones
  (si tiene rutas), Arquitectura, y Modelo de datos e Integraciones en
  WordPress.
