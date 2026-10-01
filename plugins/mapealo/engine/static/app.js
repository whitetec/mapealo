const PW = 140, PH = 48, CW = 118, CH = 36;

// ── globals mutables ──
let PILLARS = [], CHILDREN = [], ARTIFACTS = [], DEP_EDGES = [], MAP_DATA = {};
let nodeMap = {}, allNodes = [], allEdges = [];

const ART_COLORS = { image:'#38bdf8', data:'#4ade80', database:'#a78bfa', directory:'#fbbf24', document:'#f472b6', file:'#9ca3af' };
const ART_ABBR   = { image:'IMG', data:'DAT', database:'DB', directory:'DIR', document:'DOC', file:'FILE' };
function artLabel(hint) {
  const clean = hint.replace(/\/$/, '');
  const base  = clean.split('/').pop() || clean;
  const lbl   = hint.endsWith('/') ? base + '/' : base;
  return lbl.length > 22 ? '…' + lbl.slice(-20) : lbl;
}
// Estado de la vista Estructura. Se declara acá arriba y no en su bloque
// porque `loadApp` lo resetea, y `init()` corre antes de ese bloque.
// La animación de las dependencias de la vista Arquitectura se re-encadena
// sola. Hay que guardarla para poder cortarla: si no, sigue corriendo sobre
// un SVG ya borrado y le come el hilo principal al resto de las vistas.
let _depAnim = null;

let _estCollapsed = new Set();   // ids de grupo plegados
let _estIndex     = {};          // id → item ya posicionado
let _estEdgesOn   = null;        // null = lo decide el tamaño del grafo

let navHistory = [];
let zoomBehavior;
let expandedPillar = null;
let currentSim = null;

// ── refs DOM fijos ──
const elLoading  = document.getElementById('loading');
const elSelector = document.getElementById('app-select');
const elCanvas   = document.getElementById('canvas');
const elPanel    = document.getElementById('panel');
const elHint     = document.getElementById('hint');
const elTitle    = document.getElementById('app-title');
const elSubtitle = document.getElementById('app-subtitle');
const elGrid     = document.getElementById('app-grid');
const elErrMsg   = document.getElementById('error-msg');
const panelTitle = document.getElementById('panel-title');
const panelDesc  = document.getElementById('panel-desc');
const panelBody  = document.getElementById('panel-body');
const breadcrumb = document.getElementById('breadcrumb');
const elViewTabs = document.getElementById('view-tabs');

// ── vistas ──
const VIEWS = {
  estructura:    { label: 'Estructura',
                   needs: (data) => !!data?.groups?.length },
  secciones:     { label: 'Secciones',
                   needs: (data) => !!data?.map?._views?.secciones?.children?.length },
  arquitectura:  { label: 'Arquitectura',    needs: () => true },
  modelo_datos:  { label: 'Modelo de datos',
                   needs: (data) => !!data?.map?._views?.modelo_datos?.entities?.length },
  integraciones: { label: 'Integraciones',
                   needs: (data) => !!data?.map?._views?.integraciones?.external_systems?.length },
  'diseño':      { label: 'Diseño',
                   needs: (data) => !!data?.map?._views?.['diseño']?.children?.length },
  flujo:         { label: 'Flujo',           needs: (data) => !!data?.map?._views?.flujo },
};
let _currentView = 'arquitectura';
let _viewFromUrl = false;   // true si la URL fijó la vista explícitamente
let _currentMapData = null;
let _arquitecturaEdges = null;  // {ownsEdges, depEdges} cacheados

// Devuelve null si la URL no fija vista, para que loadApp pueda elegir la
// mejor disponible según lo que tenga el mapa.
function _readViewFromUrl() {
  const v = new URLSearchParams(window.location.search).get('view');
  return (v && v in VIEWS) ? v : null;
}

// Orden de preferencia cuando la URL no manda: la contención por paquete es
// la que sirve para encontrar un módulo, así que va primera.
const VIEW_DEFAULT_ORDER = ['estructura', 'arquitectura'];

function _defaultView(data) {
  return VIEW_DEFAULT_ORDER.find(v => VIEWS[v]?.needs(data)) || 'arquitectura';
}

function _setViewInUrl(view) {
  const params = new URLSearchParams(window.location.search);
  if (view === _defaultView(_currentMapData)) params.delete('view');
  else params.set('view', view);
  const qs = params.toString();
  window.history.replaceState({}, '', qs ? `/?${qs}` : '/');
}

// Cuando una vista no está disponible distinguimos:
//   - VIEW_NOT_IMPL: el frontend todavía no la implementó (v1.6 en progreso)
//   - VIEW_NO_DATA:  está implementada pero esta app no la tiene generada
const VIEW_NOT_IMPL = new Set(['flujo']);

function updateViewTabs(data, kind) {
  // Las pestañas aparecen cuando hay más de una perspectiva servible. Antes
  // se mostraban solo para WordPress y una app Python quedaba con una sola
  // vista aunque el mapa tuviera datos para otra.
  const isWp       = kind && kind.startsWith('wordpress');
  const disponibles = Object.keys(VIEWS).filter(v => VIEWS[v].needs(data));
  if (!isWp && disponibles.length < 2) {
    elViewTabs.classList.add('hidden');
    return;
  }
  elViewTabs.classList.remove('hidden');
  elViewTabs.querySelectorAll('.view-tab').forEach(btn => {
    const v   = btn.dataset.view;
    const cfg = VIEWS[v];
    const ready = cfg.needs(data);
    btn.disabled = !ready;
    if (ready) {
      btn.removeAttribute('title');
    } else if (VIEW_NOT_IMPL.has(v)) {
      btn.title = 'próximamente';
    } else {
      btn.title = 'no disponible para esta app — regenerar el mapa';
    }
    btn.classList.toggle('active', v === _currentView);
  });
}

elViewTabs.addEventListener('click', (ev) => {
  const btn = ev.target.closest('.view-tab');
  if (!btn || btn.disabled) return;
  const v = btn.dataset.view;
  if (v === _currentView) return;
  _currentView  = v;
  _viewFromUrl  = true;
  _estCollapsed = new Set();
  _estAutoHecho = null;
  _setViewInUrl(v);
  updateViewTabs(_currentMapData, _currentMapData?.kind);
  // Cerramos panel previo y limpiamos breadcrumb al cambiar de vista
  elPanel.classList.remove('open');
  navHistory = [];
  renderBreadcrumb();
  renderView(v);
});

elTitle.addEventListener('click', () => { window.history.pushState({}, '', '/'); showSelector(); });

// ── init ──
async function init() {
  const params   = new URLSearchParams(window.location.search);
  const appParam = params.get('app');
  const fromUrl = _readViewFromUrl();
  _viewFromUrl  = !!fromUrl;
  _currentView  = fromUrl || 'arquitectura';
  if (appParam) await loadApp(appParam);
  else           await showSelector();
  elLoading.classList.add('hidden');
}

// ── selector ──
async function showSelector() {
  elCanvas.classList.add('hidden');
  elPanel.classList.remove('open');
  elHint.style.display  = 'none';
  elSubtitle.textContent = 'seleccioná una app';
  elTitle.textContent    = 'jarvis-map';
  document.title         = 'jarvis-map';
  breadcrumb.textContent = '';
  document.getElementById('stale-banner').classList.remove('show');
  elViewTabs.classList.add('hidden');
  clearChildren(elGrid);
  elErrMsg.style.display = 'none';
  elSelector.classList.remove('hidden');

  let apps;
  try   { apps = await fetch('/api/apps').then(r => r.json()); }
  catch { showError('No se pudo conectar con el servidor'); return; }

  apps.forEach(a => {
    const mapped = a.mapped;
    const stale  = a.stale;
    const state  = !mapped ? 'none' : stale ? 'stale' : 'ok';

    const card = document.createElement('div');
    card.className = `app-card card-${state}`;
    if (mapped) {
      card.addEventListener('click', () => {
        window.history.pushState({}, '', `/?app=${a.id}`);
        loadApp(a.id);
      });
    }

    const nameEl = document.createElement('div');
    nameEl.className   = 'app-card-name';
    nameEl.textContent = (a.display && a.display !== a.id) ? a.display : a.id;

    const statusRow = document.createElement('div');
    statusRow.className = 'app-card-status';

    const dot = document.createElement('span');
    dot.className = `status-dot ${state}`;

    const stxt = document.createElement('span');
    stxt.className = `status-text ${state}`;
    stxt.textContent = state === 'ok' ? 'MAPEADO' : state === 'stale' ? 'DESACTUALIZADO' : 'SIN MAPA';

    statusRow.appendChild(dot);
    statusRow.appendChild(stxt);

    card.appendChild(nameEl);
    card.appendChild(statusRow);

    if (mapped) {
      const meta = document.createElement('div');
      meta.className = 'app-card-meta';

      if (a.depth) {
        const dp = document.createElement('span');
        dp.className   = `meta-pill ${a.depth === 'profundo' ? 'depth-p' : 'depth-b'}`;
        dp.textContent = a.depth;
        meta.appendChild(dp);
      }
      if (a.stack && a.stack !== 'unknown') {
        const st = document.createElement('span');
        st.className   = 'meta-pill';
        st.textContent = a.stack;
        meta.appendChild(st);
      }
      if (a.modules) {
        const mo = document.createElement('span');
        mo.className   = 'meta-pill';
        mo.textContent = `${a.modules} módulos`;
        meta.appendChild(mo);
      }

      const verMismatch = a.tool_version && a.tool_version !== a.current_tool;
      const vp = document.createElement('span');
      vp.className   = `meta-pill ${verMismatch ? 'ver-new' : 'ver'}`;
      vp.textContent = a.tool_version
        ? (verMismatch ? `v${a.tool_version} → v${a.current_tool}` : `v${a.tool_version}`)
        : '—';
      vp.title = verMismatch ? 'Mapa generado con versión anterior del tool' : '';
      meta.appendChild(vp);

      card.appendChild(meta);

      if (a.generated_at) {
        const age = document.createElement('div');
        age.className   = 'app-card-age';
        age.textContent = `generado ${relTime(a.generated_at)}`;
        card.appendChild(age);
      }
    }

    if (!mapped || stale) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn-regen' + (stale ? ' primary' : '');
      btn.textContent = mapped ? 'Regenerar' : 'Mapear';
      btn.addEventListener('click', async (ev) => {
        ev.stopPropagation();
        await regenerateApp(a.id, btn);
        await refreshSelector();
      });
      card.appendChild(btn);
    }

    elGrid.appendChild(card);
  });
}

async function regenerateApp(appId, btn) {
  if (btn) { btn.disabled = true; btn.textContent = 'Mapeando…'; }
  try {
    const r = await fetch(`/api/regenerate?app=${encodeURIComponent(appId)}&depth=basico`, { method: 'POST' });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      alert(`Error al regenerar: ${err.detail || r.status}`);
    }
  } catch (e) {
    alert('No se pudo regenerar: ' + e.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function refreshSelector() {
  // Re-fetch /api/apps y reconstruir el grid (sin tocar URL ni vista)
  if (!elSelector.classList.contains('hidden')) await showSelector();
}

function relTime(iso) {
  if (!iso) return '';
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 3600)  return `hace ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `hace ${Math.floor(diff / 3600)} h`;
  const d = Math.floor(diff / 86400);
  return `hace ${d} día${d !== 1 ? 's' : ''}`;
}

function showError(msg) {
  elErrMsg.style.display = 'block';
  elErrMsg.textContent   = msg;
}

function clearChildren(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
}

// ── load app ──
async function loadApp(appName) {
  elSelector.classList.add('hidden');
  elLoading.classList.remove('hidden');

  let data;
  try {
    const resp = await fetch(`/api/graph?app=${encodeURIComponent(appName)}`);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      elLoading.classList.add('hidden');
      elSelector.classList.remove('hidden');
      showError(err.detail || `Error ${resp.status} al cargar el mapa`);
      return;
    }
    data = await resp.json();
  } catch {
    elLoading.classList.add('hidden');
    elSelector.classList.remove('hidden');
    showError('No se pudo cargar el mapa');
    return;
  }

  PILLARS   = data.pillars   || [];
  CHILDREN  = data.children  || [];
  ARTIFACTS = data.artifacts || [];
  DEP_EDGES = data.deps      || [];
  MAP_DATA  = data.map       || {};
  navHistory = [];
  nodeMap    = {};
  // El plegado es por app: sin esto, cargar otra app deja pre-plegado
  // cualquier grupo cuyo id coincida (`app`, `scripts`, `services`).
  _estCollapsed = new Set();
  _estEdgesOn   = null;
  _estAutoHecho = null;

  PILLARS.forEach(p => {
    p.type = 'pillar';
    p.x    = p.position?.x ?? 400;
    p.y    = p.position?.y ?? 300;
    nodeMap[p.id] = p;
  });
  CHILDREN.forEach(c => {
    c.type = 'child';
    c.x    = c.position?.x ?? 400;
    c.y    = c.position?.y ?? 300;
    const par = PILLARS.find(p => p.id === c.parent);
    c.color = par?.color || '#58a6ff';
    c.glow  = par?.glow  || '#58a6ff';
    nodeMap[c.id] = c;
  });

  ARTIFACTS.forEach(art => {
    const color   = ART_COLORS[art.artifact_type] || '#9ca3af';
    const firstMod = art.modules[0] ? nodeMap[art.modules[0]] : null;
    nodeMap[art.id] = {
      ...art, type: 'artifact',
      label: artLabel(art.path_hint),
      color, glow: color,
      x: firstMod ? firstMod.x + 80 : 400,
      y: firstMod ? firstMod.y + 80 : 300,
    };
  });

  allNodes = [...PILLARS, ...CHILDREN, ...ARTIFACTS.map(a => nodeMap[a.id])];
  const ownsEdges = CHILDREN.map(c => ({ source: c.parent, target: c.id, type: 'owns' }));
  const depEdges  = DEP_EDGES.map(e => ({ ...e, type: 'dep' }));
  const artEdgesLoad = ARTIFACTS.flatMap(art =>
    art.modules.map(mid => ({
      source: art.op === 'write' ? mid    : art.id,
      target: art.op === 'write' ? art.id : mid,
      type: 'artifact', op: art.op,
    }))
  );
  allEdges = [...ownsEdges, ...depEdges, ...artEdgesLoad];

  // Guardamos los edges precomputados para que renderView() pueda re-renderizar
  // arquitectura sin reconstruir.
  _arquitecturaEdges = { ownsEdges, depEdges };

  const display = data.app_display || appName;
  elTitle.textContent    = display;
  elSubtitle.textContent = appName;
  document.title         = display + ' — jarvis-map';
  breadcrumb.textContent = '';

  // Banner stale: visible si meta.last_changelog_entry < última entrada del CHANGELOG
  // (esa info la trae /api/apps; refrescamos comparando contra esa lista)
  await updateStaleBanner(appName);

  // View tabs: solo se muestran para kind=wordpress[-remote]
  _currentMapData = data;
  // Si el view leído de URL ya no está disponible para este app, fallback
  if (!_viewFromUrl || !VIEWS[_currentView]?.needs(data)) _currentView = _defaultView(data);
  updateViewTabs(data, data.kind);

  elLoading.classList.add('hidden');
  elCanvas.classList.remove('hidden');
  elHint.style.display = 'block';

  elHint.textContent = 'hover para enfocar · click para fijar detalle · 2 niveles visibles · scroll zoom · arrastrar';
  renderView(_currentView);
}

// ── Dispatcher de vistas ──
function renderView(view) {
  if (view !== 'estructura' && view !== 'secciones' && view !== 'diseño')
    document.getElementById('est-controls')?.classList.add('hidden');
  if (view === 'estructura')          renderEstructura();
  else if (view === 'secciones')      renderSecciones();
  else if (view === 'diseño')         renderDiseno();
  else if (view === 'modelo_datos')   renderModeloDatos();
  else if (view === 'integraciones')  renderIntegraciones();
  else {
    const e = _arquitecturaEdges || { ownsEdges: [], depEdges: [] };
    renderGraph(e.ownsEdges, e.depEdges);
  }
}

// Helper para vistas no-arquitectura: limpia el SVG, instala zoom y devuelve
// las refs comunes. Cada renderer agrega sus markers/groups encima del `g`.
function _resetCanvas({ scaleMin = 0.2, scaleMax = 3 } = {}) {
  const svgEl = document.getElementById('main-svg');
  if (_depAnim) { _depAnim.interrupt(); _depAnim = null; }
  while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);
  if (currentSim) { currentSim.stop(); currentSim = null; }
  d3.select(svgEl).on('.zoom', null);

  const svg = d3.select(svgEl);
  const g   = svg.append('g');
  zoomBehavior = d3.zoom().scaleExtent([scaleMin, scaleMax])
    .on('zoom', e => g.attr('transform', e.transform));
  svg.call(zoomBehavior);

  const defs = svg.append('defs');
  return { svg, g, defs, svgEl, W: svgEl.clientWidth, H: svgEl.clientHeight };
}

// Pattern: las vistas alternativas (modelo_datos, integraciones) construyen
// nodos "sintéticos" con la shape mínima que `renderPanelFor` espera para
// poder reusarlo: {id, label, type, desc, tags, color, glow}. El panel ignora
// campos extras. Si la shape diverge demasiado, hacer una panel API explícita.

const elStaleBanner = document.getElementById('stale-banner');
const elBtnRegenApp = document.getElementById('btn-regen-app');
let _currentApp = null;

async function updateStaleBanner(appName) {
  _currentApp = appName;
  try {
    const apps = await fetch('/api/apps').then(r => r.json());
    const a = apps.find(x => x.id === appName);
    elStaleBanner.classList.toggle('show', !!(a && a.stale));
  } catch { elStaleBanner.classList.remove('show'); }
}

elBtnRegenApp.addEventListener('click', async () => {
  if (!_currentApp) return;
  await regenerateApp(_currentApp, elBtnRegenApp);
  elBtnRegenApp.textContent = 'Regenerar';
  await loadApp(_currentApp);
});

// ── Red clásica con simulación de fuerzas ──
function renderGraph(ownsEdges, depEdges) {
  if (currentSim) { currentSim.stop(); currentSim = null; }
  // Un re-render de esta misma vista apilaba otra cadena de animación encima
  if (_depAnim) { _depAnim.interrupt(); _depAnim = null; }

  const canvasEl = document.getElementById('canvas');
  const W = canvasEl.clientWidth, H = canvasEl.clientHeight;
  const svgEl = document.getElementById('main-svg');
  while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);
  d3.select(svgEl).on('.zoom', null);

  const svg = d3.select(svgEl);
  const g   = svg.append('g');

  zoomBehavior = d3.zoom().scaleExtent([0.12, 3.5])
    .on('zoom', e => g.attr('transform', e.transform));
  svg.call(zoomBehavior);

  // Defs
  const defs = svg.append('defs');
  const rg = defs.append('radialGradient').attr('id','bg').attr('cx','50%').attr('cy','50%');
  rg.append('stop').attr('offset','0%').attr('stop-color','#0d1f3c').attr('stop-opacity',.6);
  rg.append('stop').attr('offset','100%').attr('stop-color','#060d18').attr('stop-opacity',0);
  svg.insert('rect',':first-child').attr('width','100%').attr('height','100%').attr('fill','url(#bg)');

  function mkArrow(id, color) {
    defs.append('marker').attr('id',id).attr('viewBox','0 -4 8 8').attr('refX',7)
      .attr('markerWidth',5).attr('markerHeight',5).attr('orient','auto')
      .append('path').attr('d','M0,-4L8,0L0,4').attr('fill',color);
  }
  mkArrow('arr-owns','#21262d');
  const depArrowIds = {};
  [...new Set(depEdges.map(e => e.source))].forEach(src => {
    const col  = nodeMap[src]?.glow || '#58a6ff';
    const sid  = 'arr-dep-' + src.replace(/[^a-z0-9]/gi,'_');
    mkArrow(sid, col + '88');
    depArrowIds[src] = sid;
  });

  // Copias para el sim (D3 mutará source/target a objetos)
  const simOwns  = ownsEdges.map(e => ({...e}));
  const simDeps  = depEdges.map(e => ({...e}));
  const artNodes = allNodes.filter(n => n.type === 'artifact');
  const artEdges = allEdges.filter(e => e.type === 'artifact');
  const simArts  = artEdges.map(e => ({...e}));

  // Capas
  const linkG    = g.append('g');
  const artLinkG = g.append('g');
  const nodeGrp  = g.append('g');
  const artGrp   = g.append('g');
  const pingL    = g.append('g').attr('pointer-events','none');

  // Aristas de jerarquía
  const ownLines = linkG.selectAll('.link-owns').data(simOwns).enter()
    .append('line').attr('class','link link-owns')
    .attr('stroke','#21262d').attr('stroke-width',1.5)
    .attr('marker-end','url(#arr-owns)');

  // Aristas de dependencia (animadas)
  const depPaths = linkG.selectAll('.link-dep').data(simDeps).enter()
    .append('path').attr('class','link link-dep').attr('fill','none')
    .attr('stroke', d => nodeMap[d.source]?.glow || '#58a6ff')
    .attr('stroke-width',1.5).attr('stroke-dasharray','6 4')
    .attr('marker-end', d => 'url(#' + (depArrowIds[d.source] || 'arr-owns') + ')');

  _depAnim = depPaths;

  function animateDeps() {
    depPaths.transition().duration(0).attr('stroke-dashoffset',20)
      .transition().duration(1200).ease(d3.easeLinear).attr('stroke-dashoffset',0)
      .on('end', animateDeps);
  }
  animateDeps();

  // Nodos regulares (pillar + child)
  const regularNodes = allNodes.filter(n => n.type !== 'artifact');
  const nodeG = nodeGrp.selectAll('.node').data(regularNodes).enter()
    .append('g').attr('class','node').style('cursor','pointer');

  nodeG.append('rect')
    .attr('x',      d => -(d.type === 'pillar' ? PW : CW) / 2)
    .attr('y',      d => -(d.type === 'pillar' ? PH : CH) / 2)
    .attr('width',  d =>   d.type === 'pillar' ? PW : CW)
    .attr('height', d =>   d.type === 'pillar' ? PH : CH)
    .attr('rx',     d =>   d.type === 'pillar' ? 10 : 7)
    .attr('fill',   d =>   d.type === 'pillar' ? d.color + 'dd' : '#0d1117')
    .attr('stroke', d =>   d.type === 'pillar' ? d.color : d.color + '88')
    .attr('stroke-width', d => d.type === 'pillar' ? 0 : 1.5);

  nodeG.append('text')
    .attr('class', d => 'node-label' + (d.type === 'pillar' ? ' pillar' : ''))
    .attr('text-anchor','middle').attr('dy','0.35em').text(d => d.label);

  // Pulso en pilares
  nodeG.filter(d => d.type === 'pillar').each(function(d) {
    const el = d3.select(this).select('rect');
    (function pulse() {
      el.transition().duration(1800).ease(d3.easeSinInOut)
        .attr('stroke-width',2).attr('stroke',d.color)
        .transition().duration(1800).ease(d3.easeSinInOut)
        .attr('stroke-width',0).on('end', pulse);
    })();
  });

  // ── Artefactos: edges ──
  const artLines = artLinkG.selectAll('.art-link').data(simArts).enter()
    .append('line').attr('class','art-link')
    .attr('stroke', d => d.op === 'write' ? '#fbbf2488' : '#60a5fa88')
    .attr('stroke-width', 1.2).attr('stroke-dasharray','3 5')
    .style('opacity', 0.3);

  // ── Artefactos: nodos (círculos) ──
  const artG = artGrp.selectAll('.art-node').data(artNodes).enter()
    .append('g').attr('class','art-node').style('cursor','pointer').style('opacity', 0.65);

  artG.append('circle').attr('r', 20)
    .attr('fill', '#060d18').attr('stroke', d => d.color).attr('stroke-width', 1.5);

  artG.append('text')
    .attr('text-anchor','middle').attr('dy','-0.15em')
    .attr('font-size','8px').attr('font-weight','bold')
    .attr('fill', d => d.color)
    .text(d => ART_ABBR[d.artifact_type] || 'F');

  artG.append('text')
    .attr('class','node-label').attr('text-anchor','middle')
    .attr('dy','14px').attr('font-size','9px').attr('fill','#8b949e')
    .text(d => d.label);

  // ── Foco 2 niveles: 100% | 100% | 50% ──
  let lockedFocus = null;

  function neighborhood2(nodeId) {
    const lvl1 = new Set([nodeId]);
    allEdges.forEach(e => {
      if (e.source === nodeId) lvl1.add(e.target);
      if (e.target === nodeId) lvl1.add(e.source);
    });
    const lvl2 = new Set([...lvl1]);
    lvl1.forEach(id => allEdges.forEach(e => {
      if (e.source === id) lvl2.add(e.target);
      if (e.target === id) lvl2.add(e.source);
    }));
    return { lvl1, lvl2 };
  }

  function edgeId(e) {
    return {
      s: typeof e.source === 'object' ? e.source.id : e.source,
      t: typeof e.target === 'object' ? e.target.id : e.target,
    };
  }

  function applyFocus(nodeId) {
    const { lvl1, lvl2 } = neighborhood2(nodeId);
    nodeG.style('opacity', d => lvl2.has(d.id) ? 1 : 0.5)
      .each(function(nd) {
        const rect = d3.select(this).select('rect');
        if (nd.id === nodeId) {
          rect.attr('stroke', nd.glow || nd.color || '#58a6ff')
            .attr('stroke-width',3)
            .style('filter', `drop-shadow(0 0 10px ${nd.glow || '#58a6ff'})`);
        } else if (lvl1.has(nd.id)) {
          rect.attr('stroke', nd.glow || nd.color || '#58a6ff')
            .attr('stroke-width',2.5)
            .style('filter', `drop-shadow(0 0 5px ${nd.glow || '#58a6ff'}55)`);
        } else {
          rect.attr('stroke', nd.type === 'pillar' ? nd.color : nd.color + '44')
            .attr('stroke-width', nd.type === 'pillar' ? 0 : 1)
            .style('filter', null);
        }
      });
    ownLines.style('opacity', e => {
      const { s, t } = edgeId(e);
      return (lvl2.has(s) && lvl2.has(t)) ? 0.7 : 0.06;
    }).attr('stroke-width', e => {
      const { s, t } = edgeId(e);
      return (lvl1.has(s) || lvl1.has(t)) ? 2.5 : 1.5;
    });
    depPaths.style('opacity', e => {
      const { s, t } = edgeId(e);
      return (lvl2.has(s) && lvl2.has(t)) ? 1 : 0.06;
    }).attr('stroke-width', e => {
      const { s, t } = edgeId(e);
      return (lvl1.has(s) || lvl1.has(t)) ? 2.5 : 1.5;
    });
    artLines.style('opacity', e => {
      const { s, t } = edgeId(e);
      return (lvl2.has(s) && lvl2.has(t)) ? 0.85 : 0.04;
    });
    artG.style('opacity', d => lvl2.has(d.id) ? 1 : 0.08)
      .each(function(nd) {
        const inFocus = nd.id === nodeId || lvl1.has(nd.id);
        d3.select(this).select('circle')
          .attr('stroke-width', inFocus ? 2.5 : 1.5)
          .style('filter', inFocus ? `drop-shadow(0 0 6px ${nd.color})` : null);
      });
  }

  function clearFocus() {
    nodeG.style('opacity',1).each(function(d) {
      d3.select(this).select('rect')
        .attr('stroke',       d.type === 'pillar' ? d.color       : d.color + '88')
        .attr('stroke-width', d.type === 'pillar' ? 0             : 1.5)
        .style('filter', null);
    });
    ownLines.style('opacity',1).attr('stroke','#21262d').attr('stroke-width',1.5);
    depPaths.style('opacity',1).attr('stroke-width',1.5);
    artLines.style('opacity', 0.3);
    artG.style('opacity', 0.65).each(function() {
      d3.select(this).select('circle').attr('stroke-width', 1.5).style('filter', null);
    });
  }

  nodeG.on('mouseenter', (evt, d) => { if (!lockedFocus) applyFocus(d.id); });
  nodeG.on('mouseleave', ()        => { if (!lockedFocus) clearFocus(); });

  // ── Simulación de fuerzas ──
  const sim = d3.forceSimulation(allNodes)
    .force('link', d3.forceLink([...simOwns, ...simDeps, ...simArts]).id(d => d.id)
      .strength(d => d.type === 'owns' ? 0.55 : d.type === 'artifact' ? 0.45 : 0.03)
      .distance(d => d.type === 'owns' ? 80 : d.type === 'artifact' ? 85 : 185))
    .force('charge', d3.forceManyBody()
      .strength(d => d.type === 'pillar' ? -500 : d.type === 'artifact' ? -40 : -130))
    .force('x', d3.forceX(d => d.x).strength(0.09))
    .force('y', d3.forceY(d => d.y).strength(0.09))
    // Sin colisión las cajas se encimaban apenas pasaban de una docena: la
    // simulación no sabía que un nodo ocupa lugar, solo lo trataba como punto.
    .force('collide', d3.forceCollide()
      .radius(d => d.type === 'pillar' ? PW * 0.62
                 : d.type === 'artifact' ? 26
                 : CW * 0.62)
      .strength(0.85).iterations(2))
    .alphaTarget(0.018)
    .velocityDecay(0.68);

  currentSim = sim;

  sim.on('tick', () => {
    nodeG.attr('transform', d => `translate(${d.x},${d.y})`);
    artG.attr('transform',  d => `translate(${d.x},${d.y})`);
    ownLines
      .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    depPaths.attr('d', d => {
      const mx = (d.source.x + d.target.x) / 2;
      const my = (d.source.y + d.target.y) / 2 - 42;
      return `M${d.source.x},${d.source.y} Q${mx},${my} ${d.target.x},${d.target.y}`;
    });
    artLines
      .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
  });

  // Drag interactúa con el sim
  nodeG.call(d3.drag()
    .on('start', (evt, d) => {
      if (!evt.active) sim.alphaTarget(0.3).restart();
      d.fx = d.x; d.fy = d.y;
    })
    .on('drag',  (evt, d) => { d.fx = evt.x; d.fy = evt.y; })
    .on('end',   (evt, d) => {
      if (!evt.active) sim.alphaTarget(0.018);
      d.fx = null; d.fy = null;
    })
  );

  artG.call(d3.drag()
    .on('start', (evt, d) => { if (!evt.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
    .on('drag',  (evt, d) => { d.fx = evt.x; d.fy = evt.y; })
    .on('end',   (evt, d) => { if (!evt.active) sim.alphaTarget(0.018); d.fx = null; d.fy = null; })
  );
  artG.on('mouseenter', (evt, d) => { if (!lockedFocus) applyFocus(d.id); });
  artG.on('mouseleave', ()        => { if (!lockedFocus) clearFocus(); });
  artG.on('click', function(evt, d) {
    evt.stopPropagation();
    lockedFocus = d.id;
    navHistory  = [{ id: d.id, label: d.path_hint }];
    renderBreadcrumb();
    renderPanelFor(d);
    elPanel.classList.add('open');
    focusNode(d.id);
  });

  // Ping sin zoom automático
  function focusNode(id) {
    const nd = nodeMap[id];
    if (!nd) return;
    applyFocus(id);
    const r0 = nd.type === 'pillar' ? 46 : nd.type === 'artifact' ? 25 : 32;
    pingL.append('circle')
      .attr('cx', nd.x).attr('cy', nd.y).attr('r', r0)
      .attr('fill','none').attr('stroke', nd.glow || '#58a6ff')
      .attr('stroke-width',2.5).attr('opacity',0.9)
      .transition().duration(750).ease(d3.easeQuadOut)
      .attr('r', r0 + 44).attr('opacity',0).attr('stroke-width',0.5).remove();
  }

  // Click: fijar / liberar foco
  svg.on('click', () => {
    lockedFocus = null;
    clearFocus();
    elPanel.classList.remove('open');
  });

  nodeG.on('click', function(evt, d) {
    evt.stopPropagation();
    lockedFocus = d.id;
    navHistory  = [{ id: d.id, label: d.label }];
    renderBreadcrumb();
    renderPanelFor(d);
    elPanel.classList.add('open');
    focusNode(d.id);
  });

  document.getElementById('panel-close').onclick = () => {
    elPanel.classList.remove('open');
    lockedFocus = null;
    clearFocus();
  };

  window._focusNode  = focusNode;
  window._applyFocus = applyFocus;
  window._clearFocus = clearFocus;

  fitToView(50, svg, W, H);
}

// Alias mantenido por compatibilidad
function renderFlowGraph(flowOrder, ownsEdges, depEdges) {
  renderGraph(ownsEdges, depEdges);
}

// ──────────────────────────────────────────────────────────────────────────
// Vista: Modelo de datos (ER-style con D3 force layout)
// ──────────────────────────────────────────────────────────────────────────
function renderModeloDatos() {
  const view = _currentMapData?.map?._views?.modelo_datos;
  if (!view) return;

  const { svg, g, defs, W, H } = _resetCanvas();
  defs.append('marker').attr('id', 'er-arrow').attr('viewBox', '0 -4 10 8')
    .attr('refX', 9).attr('markerWidth', 7).attr('markerHeight', 7).attr('orient', 'auto')
    .append('path').attr('d', 'M0,-4L10,0L0,4').attr('fill', '#58a6ff99');

  // Nodos: cards con label + lista de fields.
  // Width considera tanto el label COMO el field más largo (en monospace
  // 10px ≈ 6.6px por char). Height tiene tope a 8 fields visibles.
  const FIELD_FONT_PX  = 10;
  const FIELD_CHAR_W   = 6.6;
  const HEADER_FONT_PX = 12;
  const HEADER_CHAR_W  = 7.5;
  const PADDING_X      = 16;
  const MAX_FIELDS     = 8;
  const ROW_HEIGHT     = 14;

  function _fieldText(f) {
    return `${f[0]}${f[1] ? ` : ${f[1]}` : ''}`;
  }

  const nodes = view.entities.map(e => {
    const visibleFields = (e.fields || []).slice(0, MAX_FIELDS);
    const headerW   = e.label.length * HEADER_CHAR_W;
    const longestF  = visibleFields.reduce((max, f) => Math.max(max, _fieldText(f).length * FIELD_CHAR_W), 0);
    const overflow  = (e.fields?.length || 0) > MAX_FIELDS ? ROW_HEIGHT : 0;
    return {
      ...e,
      width:  Math.max(150, Math.min(280, Math.ceil(Math.max(headerW, longestF) + PADDING_X * 2))),
      height: 30 + (visibleFields.length ? visibleFields.length * ROW_HEIGHT + 8 : 0) + overflow,
    };
  });
  const nodeMapER = Object.fromEntries(nodes.map(n => [n.id, n]));

  // Edges: source/target ids → refs
  const links = view.relationships
    .filter(r => nodeMapER[r.source] && nodeMapER[r.target])
    .map(r => ({ source: nodeMapER[r.source], target: nodeMapER[r.target], via: r.via }));

  // ── Layout topológico (cascada jerárquica) ──
  // Rank = longest path TO a sink usando outgoing edges.
  //   Sinks (sin outgoing) → rank 0 → ABAJO
  //   Sources (sin incoming) → rank máximo → ARRIBA
  // Lectura natural: las entidades que "usan" otras quedan arriba,
  // las que son "usadas" (FKs/taxonomías) quedan abajo.
  const incoming = {};   // id → set of source ids (para minimizar cruces)
  const outgoing = {};   // id → set of target ids (para rank)
  nodes.forEach(n => { incoming[n.id] = new Set(); outgoing[n.id] = new Set(); });
  links.forEach(l => {
    incoming[l.target.id].add(l.source.id);
    outgoing[l.source.id].add(l.target.id);
  });

  const rank = {};
  function computeRank(id, seen = new Set()) {
    if (id in rank) return rank[id];
    if (seen.has(id)) return 0;          // ciclo: cortamos
    seen.add(id);
    const outs = [...outgoing[id]];
    rank[id] = outs.length === 0 ? 0 : 1 + Math.max(...outs.map(t => computeRank(t, seen)));
    seen.delete(id);
    return rank[id];
  }
  nodes.forEach(n => computeRank(n.id));

  // Agrupar nodos por rank
  const byRank = {};
  nodes.forEach(n => { (byRank[rank[n.id]] ||= []).push(n); });
  const ranks = Object.keys(byRank).map(Number).sort((a, b) => b - a);  // descendente: top primero

  // Asignar columna dentro de cada fila intentando minimizar cruces
  ranks.forEach((r, rowIdx) => {
    if (rowIdx === 0) {
      byRank[r].sort((a, b) => a.label.localeCompare(b.label));
    } else {
      byRank[r].forEach(n => {
        // sortear por promedio de posición de padres (los que apuntan A este nodo)
        const parents = [...incoming[n.id]].map(pid => nodeMapER[pid]).filter(p => '_col' in p);
        n._sortKey = parents.length
          ? parents.reduce((s, p) => s + p._col, 0) / parents.length
          : 99999;
      });
      byRank[r].sort((a, b) => a._sortKey - b._sortKey);
    }
    byRank[r].forEach((n, i) => { n._col = i; });
  });

  // Coordenadas absolutas — top-down, fila por rank descendente
  const ROW_GAP    = 80;
  const COL_GAP    = 32;
  const TOP_MARGIN = 50;
  let yCursor = TOP_MARGIN;
  ranks.forEach(r => {
    const row     = byRank[r];
    const rowW    = row.reduce((s, n) => s + n.width, 0) + COL_GAP * (row.length - 1);
    let xCursor   = (W - rowW) / 2;
    const rowH    = Math.max(...row.map(n => n.height));
    row.forEach(n => {
      n.x  = xCursor + n.width / 2;
      n.y  = yCursor + rowH / 2;
      n.fx = n.x; n.fy = n.y;             // fijos por default; drag los libera
      xCursor += n.width + COL_GAP;
    });
    yCursor += rowH + ROW_GAP;
  });

  // Sin simulación (layout estático), pero d3.forceSimulation nos da el tick
  // loop estándar y permite drag. Charge=0 para no perturbar.
  currentSim = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).distance(0).strength(0))
    .alpha(0).stop();

  // ── Edges (bezier verticales para cascada) ──
  function _edgePath(d) {
    const s = d.source, t = d.target;
    // Borde inferior del source (apuntando "hacia abajo" del nodo)
    const sy = s.y + s.height / 2;
    const ty = t.y - t.height / 2;
    const midY = (sy + ty) / 2;
    return `M${s.x},${sy} C${s.x},${midY} ${t.x},${midY} ${t.x},${ty}`;
  }
  const edgeG = g.append('g').attr('class', 'er-edges');
  const linkSel = edgeG.selectAll('g.er-link').data(links).enter()
    .append('g').attr('class', 'er-link');
  const linkPath = linkSel.append('path')
    .attr('d', _edgePath)
    .attr('fill', 'none')
    .attr('stroke', '#58a6ff66').attr('stroke-width', 1.4)
    .attr('marker-end', 'url(#er-arrow)');
  const linkLabel = linkSel.append('text')
    .attr('class', 'er-link-label').attr('font-size', 9).attr('fill', '#8b949e')
    .attr('text-anchor', 'middle')
    .attr('x', d => (d.source.x + d.target.x) / 2)
    .attr('y', d => (d.source.y + d.source.height / 2 + d.target.y - d.target.height / 2) / 2 - 4)
    .text(d => d.via);

  // ── Nodos ──
  const nodeG = g.append('g').attr('class', 'er-nodes');
  const node = nodeG.selectAll('g.er-node').data(nodes).enter()
    .append('g').attr('class', d => `er-node er-${d.kind}`)
    .style('cursor', 'pointer')
    .call(d3.drag()
      .on('start', (e, d) => { if (!e.active) currentSim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on('drag',  (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on('end',   (e, d) => { if (!e.active) currentSim.alphaTarget(0); d.fx = null; d.fy = null; }));

  node.append('rect')
    .attr('x', d => -d.width / 2).attr('y', d => -d.height / 2)
    .attr('width', d => d.width).attr('height', d => d.height)
    .attr('rx', 8)
    .attr('fill', '#0d1117ee')
    .attr('stroke', d => d.kind === 'cpt' ? '#388bfd' : '#bf4b8a')
    .attr('stroke-width', 1.5);

  // Header (label) — usar clip path para que el texto largo no se derrame
  node.append('rect')
    .attr('x', d => -d.width / 2).attr('y', d => -d.height / 2)
    .attr('width', d => d.width).attr('height', 24).attr('rx', 8)
    .attr('fill', d => d.kind === 'cpt' ? '#1f6feb' : '#9b3a73');
  node.append('text')
    .attr('text-anchor', 'middle').attr('y', d => -d.height / 2 + 16)
    .attr('font-size', HEADER_FONT_PX).attr('font-weight', 'bold').attr('fill', '#fff')
    .text(d => d.label)
    // Si el label excede el width disponible, lo truncamos visualmente
    .each(function(d) {
      const max = d.width - PADDING_X;
      if (this.getComputedTextLength() > max) {
        const ratio = max / this.getComputedTextLength();
        const cut   = Math.max(3, Math.floor(d.label.length * ratio) - 1);
        d3.select(this).text(d.label.slice(0, cut) + '…');
      }
    });

  // Fields (solo CPTs) — el width del nodo ya está calculado para que entren.
  // Si por alguna razón siguen excediendo, getComputedTextLength + truncado.
  node.each(function(d) {
    if (d.kind !== 'cpt' || !d.fields?.length) return;
    const sel    = d3.select(this);
    const maxW   = d.width - PADDING_X;
    const visible = d.fields.slice(0, MAX_FIELDS);
    visible.forEach((f, i) => {
      const y = -d.height / 2 + 28 + i * ROW_HEIGHT + ROW_HEIGHT - 3;
      const t = sel.append('text')
        .attr('x', -d.width / 2 + PADDING_X / 2).attr('y', y)
        .attr('font-size', FIELD_FONT_PX).attr('fill', '#c9d1d9').attr('font-family', 'monospace')
        .text(_fieldText(f));
      // Trunc dinámico si el SVG real excede el width
      if (t.node().getComputedTextLength() > maxW) {
        const full = _fieldText(f);
        const ratio = maxW / t.node().getComputedTextLength();
        const cut   = Math.max(4, Math.floor(full.length * ratio) - 1);
        t.text(full.slice(0, cut) + '…');
      }
    });
    if (d.fields.length > MAX_FIELDS) {
      sel.append('text')
        .attr('x', -d.width / 2 + PADDING_X / 2).attr('y', -d.height / 2 + 28 + MAX_FIELDS * ROW_HEIGHT + ROW_HEIGHT - 3)
        .attr('font-size', 9).attr('fill', '#6e7681').attr('font-style', 'italic')
        .text(`+${d.fields.length - MAX_FIELDS} más…`);
    }
  });

  // Click → panel detail (reusa renderPanelFor con el nodo correspondiente del MAP_DATA)
  node.on('click', (ev, d) => {
    ev.stopPropagation();
    const synthetic = {
      id: d.id, label: d.label, type: 'child',
      desc: d.kind === 'cpt' ? 'Custom Post Type' : 'Taxonomía',
      tags: d.tags || [],
      color: d.kind === 'cpt' ? '#1f6feb' : '#bf4b8a',
      glow:  d.kind === 'cpt' ? '#388bfd' : '#db61a2',
    };
    renderPanelFor(synthetic);
    elPanel.classList.add('open');
  });

  // Posicionar nodos (estático — el layout ya está calculado)
  node.attr('transform', d => `translate(${d.x},${d.y})`);

  // Re-render durante drag (edges + label)
  function _refresh() {
    linkPath.attr('d', _edgePath);
    linkLabel
      .attr('x', d => (d.source.x + d.target.x) / 2)
      .attr('y', d => (d.source.y + d.source.height / 2 + d.target.y - d.target.height / 2) / 2 - 4);
    node.attr('transform', d => `translate(${d.x},${d.y})`);
  }
  currentSim.on('tick', _refresh);

  // Fit-to-view inicial: ajusta zoom para que todo el contenido entre
  setTimeout(() => {
    const bbox = g.node().getBBox();
    const padding = 40;
    const scale   = Math.min((W - padding * 2) / bbox.width, (H - padding * 2) / bbox.height, 1);
    const tx      = (W - bbox.width * scale) / 2 - bbox.x * scale;
    const ty      = (H - bbox.height * scale) / 2 - bbox.y * scale;
    svg.transition().duration(400)
      .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
  }, 50);

  // Stubs de focus (la API se usa desde renderPanelFor / breadcrumb)
  window._focusNode  = (id) => { /* TODO: highlight nodo */ };
  window._applyFocus = () => {};
  window._clearFocus = () => {};
}

// ──────────────────────────────────────────────────────────────────────────
// Vista: Integraciones (hub-spoke)
// ──────────────────────────────────────────────────────────────────────────
const INT_CATEGORY_COLORS = {
  payments:     { fill: '#238636', glow: '#56d364' },
  email:        { fill: '#1f6feb', glow: '#388bfd' },
  analytics:    { fill: '#bf4b8a', glow: '#db61a2' },
  ai:           { fill: '#8957e5', glow: '#a371f7' },
  integrations: { fill: '#9e6a03', glow: '#d29922' },
  documents:    { fill: '#bd2c00', glow: '#f85149' },
  storage:      { fill: '#4a7c7e', glow: '#56a3a6' },
  other:        { fill: '#6e7681', glow: '#8b949e' },
};

function renderIntegraciones() {
  const view = _currentMapData?.map?._views?.integraciones;
  if (!view) return;

  const { g, defs, W, H } = _resetCanvas({ scaleMin: 0.3 });
  // Marcadores: in (externo→WP) y out (WP→externo)
  ['in', 'out'].forEach(dir => {
    defs.append('marker').attr('id', `int-arr-${dir}`)
      .attr('viewBox', '0 -4 10 8').attr('refX', 9)
      .attr('markerWidth', 7).attr('markerHeight', 7).attr('orient', 'auto')
      .append('path').attr('d', 'M0,-4L10,0L0,4')
      .attr('fill', dir === 'in' ? '#56d364bb' : '#79c0ffbb');
  });

  const cx = W / 2, cy = H / 2;

  // Hub central: WordPress
  const hub = {
    id: '_hub', label: _currentMapData?.app_display || 'WordPress',
    x: cx, y: cy, type: 'hub',
  };

  // Externos en órbita exterior, distribuidos en círculo
  const externals = view.external_systems.map((e, i, arr) => {
    const angle = (2 * Math.PI * i / arr.length) - Math.PI / 2;
    const r = Math.min(W, H) * 0.36;
    return { ...e, x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle), type: 'external' };
  });
  const externalById = Object.fromEntries(externals.map(e => [e.id, e]));

  // Plugins conectores: agrupados por external, posicionados en el segmento WP↔externo
  const plugins = [];
  const byExternal = {};
  view.connections.forEach(c => {
    (byExternal[c.external] ||= []).push(c);
  });
  Object.entries(byExternal).forEach(([extId, conns]) => {
    const ext = externalById[extId];
    if (!ext) return;
    conns.forEach((c, i) => {
      // Distribuir plugins entre hub y external, con offset perpendicular si hay >1
      const t = 0.55;  // posición a lo largo de la línea
      const px = hub.x + (ext.x - hub.x) * t;
      const py = hub.y + (ext.y - hub.y) * t;
      const perpDx = -(ext.y - hub.y), perpDy = (ext.x - hub.x);
      const norm   = Math.hypot(perpDx, perpDy) || 1;
      const offset = (i - (conns.length - 1) / 2) * 26;
      plugins.push({
        id:        c.plugin,
        label:     c.plugin.replace(/^plugin:/, ''),
        x:         px + (perpDx / norm) * offset,
        y:         py + (perpDy / norm) * offset,
        external:  extId,
        direction: c.direction,
        type:      'plugin',
      });
    });
  });

  // ── Edges (líneas plugin→external en una dirección u otra) ──
  const edgeG = g.append('g').attr('class', 'int-edges');
  edgeG.selectAll('line.int-edge').data(plugins).enter()
    .append('line').attr('class', 'int-edge')
    .attr('x1', d => d.direction === 'outbound' ? d.x : externalById[d.external].x)
    .attr('y1', d => d.direction === 'outbound' ? d.y : externalById[d.external].y)
    .attr('x2', d => d.direction === 'outbound' ? externalById[d.external].x : d.x)
    .attr('y2', d => d.direction === 'outbound' ? externalById[d.external].y : d.y)
    .attr('stroke', d => d.direction === 'outbound' ? '#79c0ff77' : '#56d36477')
    .attr('stroke-width', 1.4).attr('stroke-dasharray', '4 3')
    .attr('marker-end', d => `url(#int-arr-${d.direction === 'outbound' ? 'out' : 'in'})`);

  // Líneas hub → plugin (siempre solid azul claro)
  edgeG.selectAll('line.int-hub-link').data(plugins).enter()
    .append('line').attr('class', 'int-hub-link')
    .attr('x1', hub.x).attr('y1', hub.y)
    .attr('x2', d => d.x).attr('y2', d => d.y)
    .attr('stroke', '#21262d').attr('stroke-width', 1);

  // ── Nodos ──
  const nodeG = g.append('g').attr('class', 'int-nodes');

  // Hub
  const hubG = nodeG.append('g').attr('transform', `translate(${hub.x},${hub.y})`);
  hubG.append('circle').attr('r', 50)
    .attr('fill', '#0d1f3c').attr('stroke', '#58a6ff').attr('stroke-width', 2.5);
  hubG.append('text').attr('text-anchor', 'middle').attr('dy', '.35em')
    .attr('font-size', 13).attr('font-weight', 'bold').attr('fill', '#79c0ff')
    .text('WordPress');
  hubG.append('text').attr('text-anchor', 'middle').attr('y', 16)
    .attr('font-size', 10).attr('fill', '#8b949e')
    .text(hub.label);

  // Externals
  const extG = nodeG.selectAll('g.int-ext').data(externals).enter()
    .append('g').attr('class', 'int-ext')
    .attr('transform', d => `translate(${d.x},${d.y})`)
    .style('cursor', 'pointer');
  extG.append('circle').attr('r', 36)
    .attr('fill', d => INT_CATEGORY_COLORS[d.category]?.fill || '#444')
    .attr('stroke', d => INT_CATEGORY_COLORS[d.category]?.glow || '#888').attr('stroke-width', 2);
  extG.append('text').attr('text-anchor', 'middle').attr('dy', '.35em')
    .attr('font-size', 11).attr('font-weight', 'bold').attr('fill', '#fff')
    .text(d => d.label);
  extG.append('text').attr('text-anchor', 'middle').attr('y', 13)
    .attr('font-size', 9).attr('fill', '#ffffffaa')
    .text(d => d.category);

  // Plugins
  const pluginG = nodeG.selectAll('g.int-plugin').data(plugins).enter()
    .append('g').attr('class', 'int-plugin')
    .attr('transform', d => `translate(${d.x},${d.y})`)
    .style('cursor', 'pointer');
  pluginG.append('rect').attr('x', -55).attr('y', -12).attr('width', 110).attr('height', 24).attr('rx', 6)
    .attr('fill', '#0d1117').attr('stroke', '#30363d').attr('stroke-width', 1);
  pluginG.append('text').attr('text-anchor', 'middle').attr('dy', '.35em')
    .attr('font-size', 10).attr('fill', '#c9d1d9').attr('font-family', 'monospace')
    .text(d => d.label.length > 16 ? d.label.slice(0, 14) + '…' : d.label);

  // Click → panel
  pluginG.on('click', (ev, d) => {
    ev.stopPropagation();
    const synthetic = {
      id: d.id, label: d.label.replace(/^plugin:/, ''), type: 'child',
      desc: d.direction === 'outbound' ? `Outbound → ${externalById[d.external].label}`
                                       : `Inbound ← ${externalById[d.external].label}`,
      tags: ['plugin', d.direction],
      color: '#1f6feb', glow: '#388bfd',
    };
    renderPanelFor(synthetic);
    elPanel.classList.add('open');
  });

  // Click en external → panel
  extG.on('click', (ev, d) => {
    ev.stopPropagation();
    const synthetic = {
      id: d.id, label: d.label, type: 'child',
      desc: `Sistema externo · ${d.category}`,
      tags: [d.category],
      color: INT_CATEGORY_COLORS[d.category]?.fill, glow: INT_CATEGORY_COLORS[d.category]?.glow,
    };
    renderPanelFor(synthetic);
    elPanel.classList.add('open');
  });

  window._focusNode  = () => {};
  window._applyFocus = () => {};
  window._clearFocus = () => {};
}

function fitToView(padding, svg, W, H) {
  if (!allNodes.length || !zoomBehavior) return;
  const xs = allNodes.map(n => n.x), ys = allNodes.map(n => n.y);
  const x0 = Math.min(...xs) - PW/2 - padding, y0 = Math.min(...ys) - PH/2 - padding;
  const x1 = Math.max(...xs) + PW/2 + padding, y1 = Math.max(...ys) + PH/2 + padding;
  const bw = x1 - x0, bh = y1 - y0;
  const scale = Math.min(W / bw, H / bh, 1);
  const tx = (W - bw * scale) / 2 - x0 * scale;
  const ty = (H - bh * scale) / 2 - y0 * scale;
  svg.call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
}

// ── panel ──
function chip(label, cls, tip) {
  const s = document.createElement('span');
  s.className   = 'chip ' + cls + (tip ? ' chip-tooltip' : '');
  s.textContent = label;
  if (tip) s.setAttribute('data-tip', tip);
  return s;
}

function navChip(label, nodeId, cls) {
  const s = document.createElement('span');
  s.className   = 'chip chip-nav ' + cls;
  s.textContent = label;
  s.title = 'Ver en el mapa';
  s.addEventListener('click', evt => {
    evt.stopPropagation();
    const nd = nodeMap[nodeId];
    if (!nd) return;
    navHistory.push({ id: nodeId, label: nd.label });
    renderBreadcrumb();
    if (window._focusNode) window._focusNode(nodeId);
    renderPanelFor(nd);
    elPanel.classList.add('open');
  });
  return s;
}

function openChip(label, cls, tip, openPath) {
  const s = document.createElement('span');
  s.className   = 'chip chip-open ' + cls + (tip ? ' chip-tooltip' : '');
  s.textContent = label;
  if (tip) s.setAttribute('data-tip', tip);
  s.title = 'Abrir ' + openPath;
  s.addEventListener('click', evt => {
    evt.stopPropagation();
    fetch('/api/open?path=' + encodeURIComponent(openPath), { method: 'POST' })
      .then(r => { if (!r.ok) console.warn('open falló', r.status); })
      .catch(err => console.warn('open error', err));
  });
  return s;
}

function mkSection(title, chips) {
  if (!chips.length) return null;
  const div = document.createElement('div');
  div.className = 'rel-section';
  const lbl = document.createElement('div');
  lbl.className   = 'rel-label';
  lbl.textContent = title;
  div.appendChild(lbl);
  chips.forEach(c => div.appendChild(c));
  return div;
}

// ── caja de instrucción: clic en un componente y hablarle a la sesión ──
// El sub-componente elegido acota la referencia a su rango de líneas; el
// backend lo resuelve contra el archivo real, no contra el mapa, así que el
// rango es correcto aunque el mapa esté viejo.
let _sub = null;

function subChip(label, cls, tip, kind) {
  const nombre = kind === 'route'
    ? label.replace(/^[A-Z]+\s+/, '')   // "POST /api/enviar" → "/api/enviar"
    : label.split('(')[0].trim();       // "componer(a, b)"    → "componer"
  const s = chip(label, cls, tip);
  s.classList.add('chip-sub');
  s.addEventListener('click', evt => {
    evt.stopPropagation();
    const yaEstaba = _sub && _sub.name === nombre;
    document.querySelectorAll('.chip-sub.sel').forEach(c => c.classList.remove('sel'));
    if (yaEstaba) { _sub = null; }
    else { _sub = { kind, name: nombre }; s.classList.add('sel'); }
    actualizarPreview();
  });
  return s;
}

// Estado del canal. La referencia se escribe relativa al cwd de la sesión, que
// es como Claude Code resuelve un @path, así que el preview tiene que mostrar
// la misma ruta que se va a mandar y no solo el rel_path dentro de la app.
let _destino = { via: 'portapapeles', cwd: null, apps_dir: '' };

function refrescarDestino() {
  return fetch('/api/destino')
    .then(r => r.json())
    .then(j => { _destino = j; actualizarPreview(); })
    .catch(() => {});
}

function rutaVisible(rel) {
  if (!_destino.apps_dir) return rel;
  const abs = _destino.apps_dir + '/' + _currentApp + '/' + rel;
  if (_destino.cwd && abs.startsWith(_destino.cwd + '/')) {
    return abs.slice(_destino.cwd.length + 1);
  }
  return abs;
}

function actualizarPreview() {
  const prev = document.getElementById('nav-ref');
  if (!prev || !window._nodoActual) return;
  const rel = window._nodoActual.rel_path;
  prev.textContent = rel
    ? '@' + rutaVisible(rel) + (_sub ? '  → ' + _sub.name : '')
    : '[' + window._nodoActual.label + ']';
  prev.classList.toggle('nav-ref-sin-sesion', _destino.via !== 'kitty');
  prev.title = _destino.via === 'kitty'
    ? 'Va al prompt de la sesión que abrió el mapa'
    : 'Sin sesión registrada: se va a copiar al portapapeles';
}

function mkEnviar(d) {
  const box = document.createElement('div');
  box.className = 'nav-box';

  const lbl = document.createElement('div');
  lbl.className = 'rel-label';
  lbl.textContent = 'Instrucción';
  box.appendChild(lbl);

  const ref = document.createElement('div');
  ref.id = 'nav-ref';
  ref.className = 'nav-ref';
  box.appendChild(ref);

  const ta = document.createElement('textarea');
  ta.className = 'nav-ta';
  ta.rows = 3;
  ta.placeholder = 'Qué hacer con este componente…';
  box.appendChild(ta);

  const fila = document.createElement('div');
  fila.className = 'nav-fila';

  const estado = document.createElement('span');
  estado.className = 'nav-estado';

  const mandar = (enter, btn) => {
    const txt = ta.value.trim();
    if (!txt) { ta.focus(); return; }
    [...fila.querySelectorAll('button')].forEach(b => b.disabled = true);
    estado.textContent = '…';
    fetch('/api/enviar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        // Una hoja de Secciones tiene id propio por endpoint; el backend
        // resuelve la ruta del archivo por el nodo del graph.
        app: _currentApp, node: d.node_id || d.id,
        sub: _sub, instruccion: txt, enter: enter,
      }),
    })
      .then(async r => {
        const j = await r.json().catch(() => ({}));
        if (j.via === 'kitty') {
          estado.textContent = enter ? 'enviado' : 'escrito en el prompt';
          estado.className   = 'nav-estado ok';
          ta.value = '';
        } else if (j.via === 'portapapeles') {
          estado.textContent = 'sin sesión: copiado, pegá con Ctrl+Shift+V';
          estado.className   = 'nav-estado warn';
        } else {
          estado.textContent = j.detail || j.detalle || 'no se pudo entregar';
          estado.className   = 'nav-estado err';
        }
      })
      .catch(() => { estado.textContent = 'error de red'; estado.className = 'nav-estado err'; })
      .then(() => { [...fila.querySelectorAll('button')].forEach(b => b.disabled = false); });
  };

  const bEscribir = document.createElement('button');
  bEscribir.className   = 'nav-btn';
  bEscribir.textContent = 'Escribir';
  bEscribir.title = 'Deja el texto en el prompt para que lo revises';
  bEscribir.addEventListener('click', () => mandar(false, bEscribir));

  const bEnviar = document.createElement('button');
  bEnviar.className   = 'nav-btn nav-btn-primario';
  bEnviar.textContent = 'Enviar';
  bEnviar.title = 'Escribe y manda el prompt';
  bEnviar.addEventListener('click', () => mandar(true, bEnviar));

  fila.appendChild(bEscribir);
  fila.appendChild(bEnviar);
  fila.appendChild(estado);
  box.appendChild(fila);
  return box;
}

function renderPanelFor(d) {
  if (d.type === 'artifact') {
    panelTitle.textContent = artLabel(d.path_hint);
    panelDesc.textContent  = `${d.artifact_type} · ${d.op === 'write' ? 'generado' : 'leído'}`;
    clearChildren(panelBody);
    const full = document.createElement('div');
    full.className   = 'rel-label';
    full.style.cssText = 'word-break:break-all;margin-bottom:10px;color:#8b949e';
    full.textContent = d.path_hint;
    panelBody.appendChild(full);
    const chips = d.modules.map(mid =>
      navChip(nodeMap[mid]?.label || mid, mid, d.op === 'write' ? 'chip-dep-in' : 'chip-dep-out')
    );
    const sec = mkSection(d.op === 'write' ? 'Generado por' : 'Leído por', chips);
    if (sec) panelBody.appendChild(sec);
    return;
  }

  panelTitle.textContent = d.label;
  panelDesc.textContent  = d.desc || '';
  clearChildren(panelBody);
  window._nodoActual = d;
  _sub = null;

  (d.tags || []).forEach(t => {
    const s = document.createElement('span');
    s.className   = 'chip chip-parent';
    s.style.marginTop = '6px';
    s.textContent = t;
    panelBody.appendChild(s);
  });

  const owns   = allEdges.filter(e => e.type === 'owns' && e.source === d.id).map(e => navChip(nodeMap[e.target]?.label || e.target, e.target, 'chip-owns'));
  const parent = allEdges.filter(e => e.type === 'owns' && e.target === d.id).map(e => navChip(nodeMap[e.source]?.label || e.source, e.source, 'chip-parent'));
  const depOut = allEdges.filter(e => e.type === 'dep'  && e.source === d.id).map(e => navChip(nodeMap[e.target]?.label || e.target, e.target, 'chip-dep-out'));
  const depIn  = allEdges.filter(e => e.type === 'dep'  && e.target === d.id).map(e => navChip(nodeMap[e.source]?.label || e.source, e.source, 'chip-dep-in'));

  const md = MAP_DATA[d.id] || {};

  // Secciones de relación entre nodos (siempre presentes, kind-agnostic)
  const relSections = [
    mkSection('Contiene',      owns),
    mkSection('Pertenece a',   parent),
    mkSection('Depende de',    depOut),
    mkSection('Requerido por', depIn),
  ];

  // Artefactos del propio analyzer (Python los puebla; WP por ahora no)
  const myArts   = ARTIFACTS.filter(a => a.modules.includes(d.id));
  const artWrite = myArts.filter(a => a.op === 'write').map(a =>
    chip(`${ART_ABBR[a.artifact_type] || 'F'} ${artLabel(a.path_hint)}`, 'chip-artifact-write', a.path_hint)
  );
  const artRead  = myArts.filter(a => a.op === 'read').map(a =>
    chip(`${ART_ABBR[a.artifact_type] || 'F'} ${artLabel(a.path_hint)}`, 'chip-artifact-read', a.path_hint)
  );
  const artSections = [mkSection('Genera', artWrite), mkSection('Lee', artRead)];

  // Secciones de contenido por componente:
  //   - Si el detail trae `sections` (formato data-driven), renderizar esas.
  //   - Si no, fallback al esquema python legacy (fn/models/routes/vars).
  let contentSections = [];
  if (Array.isArray(md.sections)) {
    contentSections = md.sections.map(sec =>
      mkSection(sec.label, (sec.items || []).map(item => {
        const n = item[0], t = item[1] || '', openPath = item[2] || '';
        const cls = sec.chip_class || 'chip-var';
        return openPath ? openChip(n, cls, t, openPath) : chip(n, cls, t);
      }))
    );
  } else {
    const fns    = (md.fn     || []).map(([n, t]) => subChip(n, 'chip-fn',    t, 'fn'));
    const models = (md.models || []).map(([n, t]) => subChip(n, 'chip-model', t, 'model'));
    const routes = (md.routes || []).map(([n, t]) => subChip(n, 'chip-route', t, 'route'));
    const vars   = (md.vars   || []).map(([n, t]) => chip(n, 'chip-var',   t));
    contentSections = [
      mkSection('Funciones', fns),
      mkSection('Modelos',   models),
      mkSection('Rutas',     routes),
      mkSection('Variables', vars),
    ];
  }

  [...relSections, ...artSections, ...contentSections]
    .forEach(s => { if (s) panelBody.appendChild(s); });

  panelBody.appendChild(mkEnviar(d));
  actualizarPreview();
  refrescarDestino();
}

// ── breadcrumb ──
function renderBreadcrumb() {
  clearChildren(breadcrumb);
  navHistory.forEach((item, i) => {
    const span = document.createElement('span');
    span.className   = 'bc-item' + (i === navHistory.length - 1 ? ' active' : '');
    span.textContent = item.label;
    if (i < navHistory.length - 1) {
      span.addEventListener('click', () => {
        navHistory = navHistory.slice(0, i + 1);
        if (window._focusNode) window._focusNode(item.id);
        renderPanelFor(nodeMap[item.id]);
        renderBreadcrumb();
      });
    }
    breadcrumb.appendChild(span);
    if (i < navHistory.length - 1) {
      const sep = document.createElement('span');
      sep.className   = 'bc-sep';
      sep.textContent = '›';
      breadcrumb.appendChild(sep);
    }
  });
  const hh = document.querySelector('header').offsetHeight;
  elCanvas.style.height   = `calc(100vh - ${hh}px)`;
  elPanel.style.top       = `${hh}px`;
  elPanel.style.height    = `calc(100vh - ${hh}px)`;
}

window.addEventListener('popstate', () => init());
init();

// ══════════════════════════════════════════════════════════════════════════
// Vista Estructura — contención por paquete
//
// Cada caja es un directorio real del proyecto y cada caja adentro es un
// archivo. Las flechas son imports resueltos por ruta de módulo.
//
// El layout se calcula, no se simula: cada grupo mide lo que ocupan sus hijos
// y los acomoda en filas. Dos nodos no pueden encimarse por construcción, que
// es lo que le pasaba a la vista orbital cuando pasaba de una docena de
// módulos.
// ══════════════════════════════════════════════════════════════════════════

const EST = {
  LEAF_W: 152, LEAF_H: 30, GAP: 9,
  PAD: 13, HEADER: 27, ASPECT: 1.75,
  MIN_GROUP_W: 120,
};


function _estTree(fuente) {
  const groups = fuente.groups || [];
  if (!groups.length) return null;

  const byId = {};
  groups.forEach(g => { byId[g.id] = { ...g, kind: 'group', subs: [], leaves: [] }; });

  let root = groups.map(g => byId[g.id]).find(n => n.parent == null) || null;
  if (!root) {
    root = { id: '__root__', label: fuente.rootLabel || 'app',
             parent: null, depth: 0, kind: 'group', subs: [], leaves: [] };
    byId[root.id] = root;
  }
  groups.forEach(g => {
    const n = byId[g.id];
    if (n === root) return;
    // Un grupo cuyo padre no existe cuelga de la raíz. Antes quedaba huérfano
    // y no se dibujaba, sin ningún aviso.
    (byId[g.parent] || root).subs.push(n);
  });

  // Color heredado del grupo de primer nivel
  const paint = (n, color) => {
    n.color = n.color || color || '#3d5a80';
    n.subs.forEach(s => paint(s, n.color));
  };
  root.subs.forEach(s => paint(s, s.color));
  root.color = root.color || '#30435c';

  (fuente.children || []).forEach(c => {
    const g = byId[c.group] || root;
    // El color sale del directorio que lo contiene. El de `nodeMap` viene del
    // pilar heurístico, que es justo la taxonomía que esta vista deja de usar.
    g.leaves.push({ ...c, kind: 'leaf', parentGroup: g.id, estColor: g.color });
  });

  return root;
}

/** Mide un grupo de adentro hacia afuera y acomoda sus hijos en filas. */
function _estLayout(node) {
  const { LEAF_W, LEAF_H, GAP, PAD, HEADER, ASPECT, MIN_GROUP_W } = EST;

  if (_estCollapsed.has(node.id)) {
    const n = node.subs.length + node.leaves.length;
    node.items = [];
    node.w = Math.max(MIN_GROUP_W, node.label.length * 7.2 + 58);
    node.h = HEADER + 6;
    node.hiddenCount = _estCountLeaves(node);
    return node;
  }

  const subs = node.subs.map(_estLayout);
  // Todas las hojas de un grupo comparten ancho, tomado del nombre más largo:
  // la grilla queda pareja y un `observatorio_backfill.py` no se sale de su caja.
  const leafW = node.leaves.reduce(
    (w, l) => Math.max(w, l.label.length * 7.15 + 22), LEAF_W);
  const leaves = node.leaves.map(l => { l.w = leafW; l.h = LEAF_H; return l; });

  // Los subgrupos primero: son las cajas grandes y quedan mejor arriba
  subs.sort((a, b) => (b.w * b.h) - (a.w * a.h));
  leaves.sort((a, b) => a.label.localeCompare(b.label));
  const items = [...subs, ...leaves];
  node.items  = items;

  if (!items.length) {
    node.w = Math.max(MIN_GROUP_W, node.label.length * 7.2 + 24);
    node.h = HEADER + PAD;
    return node;
  }

  const area   = items.reduce((s, i) => s + (i.w + GAP) * (i.h + GAP), 0);
  const target = Math.max(...items.map(i => i.w), Math.sqrt(area * ASPECT));

  let x = 0, y = 0, rowH = 0, maxW = 0;
  items.forEach(it => {
    if (x > 0 && x + it.w > target) { x = 0; y += rowH + GAP; rowH = 0; }
    it.rx = x; it.ry = y;
    x   += it.w + GAP;
    rowH = Math.max(rowH, it.h);
    maxW = Math.max(maxW, x - GAP);
  });

  node.w = maxW + PAD * 2;
  node.h = HEADER + y + rowH + PAD;
  return node;
}

function _estCountLeaves(node) {
  return node.leaves.length + node.subs.reduce((s, g) => s + _estCountLeaves(g), 0);
}

/**
 * Convierte las posiciones relativas en absolutas y arma el índice.
 *
 * Cada item guarda la cadena de grupos que lo contienen **según el árbol que
 * se dibujó**, no según el campo `group` del dato. Si un mapa trae un `group`
 * que no existe en `groups`, la hoja se ubica igual en la raíz y su cadena
 * refleja eso, así que el plegado sigue siendo correcto.
 */
function _estPlace(node, ox, oy, chain = []) {
  node.ax = ox; node.ay = oy;
  node.cx = ox + node.w / 2;
  node.cy = oy + node.h / 2;
  node.chain = chain;
  _estIndex[node.id] = node;

  const propia = [...chain, node.id];

  if (_estCollapsed.has(node.id)) _estRegistrarOcultos(node, propia);

  (node.items || []).forEach(it => {
    const x = ox + EST.PAD + it.rx;
    const y = oy + EST.HEADER + it.ry;
    if (it.kind === 'group') _estPlace(it, x, y, propia);
    else {
      it.ax = x; it.ay = y;
      it.cx = x + it.w / 2;
      it.cy = y + it.h / 2;
      it.chain = propia;
      _estIndex[it.id] = it;
    }
  });
}

/**
 * Nodo visible que representa a `id`. Si su grupo está plegado, el edge se
 * redirige a la caja plegada en vez de desaparecer sin aviso.
 */
/**
 * Un grupo plegado no dibuja a sus hijos, pero sus hijos siguen teniendo
 * imports. Se los indexa con su cadena de ancestros y sin posición, para que
 * `_estVisible` pueda mandar el edge a la caja plegada.
 */
function _estRegistrarOcultos(group, chain) {
  const propia = [...chain, group.id];
  group.leaves.forEach(l => { _estIndex[l.id] = { ...l, chain: propia, ax: undefined }; });
  group.subs.forEach(g => {
    _estIndex[g.id] = { ...g, chain: propia, ax: undefined };
    _estRegistrarOcultos(g, propia);
  });
}

function _estVisible(id) {
  const nodo = _estIndex[id];
  if (!nodo) return null;
  // El ancestro plegado más externo es el que lo representa en el dibujo
  const tapado = (nodo.chain || []).find(gid => _estCollapsed.has(gid));
  if (tapado) return _estIndex[tapado];
  return nodo.ax === undefined ? null : nodo;
}

const elEstCtl    = document.getElementById('est-controls');
const elEstEdges  = document.getElementById('est-show-edges');
const elEstExpand = document.getElementById('est-expand');

// Arriba de este número de imports el dibujo en reposo es una maraña, así que
// las flechas arrancan apagadas y aparecen al pasar por encima de un módulo.
const EST_EDGE_AUTO_LIMIT = 70;

elEstEdges?.addEventListener('change', () => {
  _estEdgesOn = elEstEdges.checked;
  renderContencion(_estFuente);
});
elEstExpand?.addEventListener('click', () => {
  if (_estCollapsed.size) _estCollapsed.clear();
  else _estAllGroups().forEach(id => _estCollapsed.add(id));
  renderContencion(_estFuente);
});

function _estAllGroups() {
  return (_estFuente?.groups || []).filter(g => g.depth > 0).map(g => g.id);
}

// Fuente activa del motor de contención. Las dos vistas que lo usan (la
// estructura de archivos y el espacio de URLs) traen la misma forma
// `{groups, children}`; lo único que cambia es de dónde sale y qué significa.
let _estFuente = null;

function renderEstructura() {
  renderContencion(_fuenteEstructura());
}

function renderSecciones() {
  const f = _fuenteSecciones();
  // El árbol de URLs es más profundo que el de archivos: seis niveles de caja
  // no se leen. Se abre mostrando las secciones y sus subsecciones plegadas,
  // que es como se lo usa: ver el mapa y bajar a una.
  _plegadoInicial(f, 2);
  renderContencion(f);
}

// Diseño: la web como la ve quien la visita. Un grupo por página y sus bloques
// (secciones y componentes de primer nivel) en el orden en que aparecen.
function renderDiseno() {
  const f = _fuenteDiseno();
  _plegadoInicial(f, 2);
  renderContencion(f);
}

function _fuenteDiseno() {
  const v = _currentMapData?.map?._views?.['diseño'] || {};
  return {
    id:        'diseño',
    groups:    v.groups   || [],
    children:  v.children || [],
    deps:      [],
    rootLabel: _currentMapData?.app_display || 'sitio',
    nodo: (d) => ({
      id: d.id, node_id: d.node_id, label: d.label, type: 'child',
      desc: d.desc, tags: d.tags || [], rel_path: d.rel_path, fn: d.fn,
      color: d.estColor, glow: d.estColor, url: d.url,
    }),
    hint: () => 'la caja es una página · cada bloque es una sección o un componente, en el orden en que se ve · '
      + 'click abre el detalle y referencia sus líneas',
  };
}

let _estAutoHecho = null;

function _plegadoInicial(fuente, desde) {
  const clave = `${_currentApp}:${fuente.id}`;
  if (_estAutoHecho === clave) return;
  _estAutoHecho = clave;
  _estCollapsed = new Set(
    (fuente.groups || []).filter(g => g.depth >= desde).map(g => g.id));
}

function _fuenteEstructura() {
  return {
    id:        'estructura',
    groups:    _currentMapData?.groups || [],
    children:  CHILDREN,
    deps:      DEP_EDGES || [],
    rootLabel: _currentMapData?.app_display || 'app',
    nodo:      (d) => nodeMap[d.id],
    hint:      (edges, mostrar) => 'la caja es el directorio · '
      + (mostrar ? 'la flecha es un import · ' : `${edges} imports ocultos, hover para verlos · `)
      + 'hover enfoca · click abre el detalle · click en el nombre del paquete lo pliega',
  };
}

function _fuenteSecciones() {
  const v = _currentMapData?.map?._views?.secciones || {};
  return {
    id:        'secciones',
    groups:    v.groups   || [],
    children:  v.children || [],
    deps:      [],
    rootLabel: _currentMapData?.app_display || 'sitio',
    // Nodo sintético: el panel solo necesita esta forma mínima, y `rel_path`
    // más `fn` son los que arman la referencia de /navegar.
    nodo: (d) => ({
      id: d.id, node_id: d.node_id, label: d.label, type: 'child',
      desc: d.desc, tags: d.tags || [], rel_path: d.rel_path, fn: d.fn,
      color: d.estColor, glow: d.estColor, url: d.url,
    }),
    hint: () => 'la caja es un tramo de la URL · la hoja es un endpoint · '
      + 'click abre el detalle con el archivo y la función que lo atiende',
  };
}

function renderContencion(fuente) {
  _estFuente = fuente;
  const { svg, g, defs, svgEl, W, H } = _resetCanvas({ scaleMin: 0.12, scaleMax: 4 });
  elEstCtl?.classList.remove('hidden');

  const root = _estTree(fuente);
  if (!root) {
    elHint.textContent = 'este mapa no tiene grupos — regenerar con la versión nueva';
    return;
  }

  _estIndex = {};
  _estLayout(root);
  _estPlace(root, 0, 0);

  // ── flechas ──
  const mkMarker = (id, color) => defs.append('marker')
      .attr('id', id).attr('viewBox', '0 -3 7 6')
      .attr('refX', 7).attr('refY', 0)
      .attr('markerWidth', 5).attr('markerHeight', 5)
      .attr('orient', 'auto')
    .append('path')
      .attr('d', 'M0,-3L7,0L0,3')
      .attr('fill', color);
  mkMarker('est-arrow',  '#6b7583');
  mkMarker('est-arrow-o', '#58a6ff');
  mkMarker('est-arrow-i', '#3fb950');

  const layerBoxes = g.append('g');
  const layerEdges = g.append('g').attr('class', 'est-edges');
  const layerLeaves = g.append('g');

  // ── grupos ──
  const groupList = [];
  (function walk(n) { groupList.push(n); (n.items || []).forEach(i => { if (i.kind === 'group') walk(i); }); })(root);

  const gSel = layerBoxes.selectAll('g.est-group').data(groupList, d => d.id)
    .join('g').attr('class', 'est-group')
    .attr('transform', d => `translate(${d.ax},${d.ay})`);

  gSel.append('rect')
    .attr('width', d => d.w).attr('height', d => d.h)
    .attr('rx', 8)
    .attr('fill', d => d.color)
    .attr('fill-opacity', d => d.depth === 0 ? 0.05 : 0.09)
    .attr('stroke', d => d.color)
    .attr('stroke-opacity', d => d.depth === 0 ? 0.35 : 0.55)
    .attr('stroke-width', 1);

  gSel.append('text')
    .attr('x', 11).attr('y', 18)
    .attr('class', 'est-group-label')
    .attr('fill', d => d.color)
    .text(d => {
      const n = _estCountLeaves(d);
      const caret = _estCollapsed.has(d.id) ? '▸ ' : '▾ ';
      return `${d.depth === 0 ? '' : caret}${d.label}  ${n}`;
    });

  // Click en el encabezado pliega y despliega
  gSel.filter(d => d.depth > 0)
    .append('rect')
    .attr('width', d => d.w).attr('height', EST.HEADER)
    .attr('fill', 'transparent').style('cursor', 'pointer')
    .on('click', (ev, d) => {
      ev.stopPropagation();
      if (_estCollapsed.has(d.id)) _estCollapsed.delete(d.id);
      else _estCollapsed.add(d.id);
      renderContencion(_estFuente);
    });

  // ── hojas ──
  // `ax` definido = la hoja se dibuja. Las de un grupo plegado están en el
  // índice solo para poder redirigir sus imports a la caja.
  const leaves = Object.values(_estIndex)
    .filter(n => n.kind === 'leaf' && n.ax !== undefined);

  const lSel = layerLeaves.selectAll('g.est-leaf').data(leaves, d => d.id)
    .join('g').attr('class', 'est-leaf')
    .attr('transform', d => `translate(${d.ax},${d.ay})`)
    .style('cursor', 'pointer');

  lSel.append('rect')
    .attr('width', d => d.w).attr('height', d => d.h)
    .attr('rx', 5)
    .attr('fill', '#0d1117')
    .attr('stroke', d => d.estColor || '#58a6ff')
    .attr('stroke-opacity', 0.62)
    .attr('stroke-width', 1);

  lSel.append('text')
    .attr('x', 9).attr('y', 19)
    .attr('class', 'est-leaf-label')
    .text(d => d.label);

  // ── edges de import ──
  const vistos = new Map();
  (fuente.deps || []).forEach(e => {
    const s = _estVisible(e.source), t = _estVisible(e.target);
    if (!s || !t || s === t) return;
    const key = `${s.id}->${t.id}`;
    if (!vistos.has(key)) {
      // source/target son los ids ya resueltos: el foco trabaja sobre lo que
      // se ve, y un módulo tapado no se puede enfocar.
      vistos.set(key, { id: key, source: s.id, target: t.id, s, t, n: 1 });
    } else {
      vistos.get(key).n += 1;
    }
  });
  const edges = [...vistos.values()];

  const mostrar = _estEdgesOn === null
    ? edges.length <= EST_EDGE_AUTO_LIMIT
    : _estEdgesOn;
  if (elEstEdges) {
    elEstEdges.checked = mostrar;
    elEstEdges.closest('label').style.display = (fuente.deps || []).length ? '' : 'none';
  }
  if (elEstExpand) elEstExpand.textContent = _estCollapsed.size ? 'desplegar todo' : 'plegar todo';
  const baseOp = mostrar ? 0.28 : 0;

  const ePath = layerEdges.selectAll('path').data(edges, d => d.id)
    .join('path')
    .attr('class', 'est-edge')
    .attr('fill', 'none')
    .attr('stroke', '#6b7583')
    .attr('stroke-width', 1)
    .attr('stroke-opacity', baseOp)
    .attr('marker-end', mostrar ? 'url(#est-arrow)' : null)
    .attr('d', d => _estEdgePath(d.s, d.t));

  // ── foco ──
  function estFocus(id) {
    const vecinos = new Set([id]);
    edges.forEach(e => {
      if (e.source === id) vecinos.add(e.target);
      if (e.target === id) vecinos.add(e.source);
    });
    ePath
      .attr('stroke-opacity', d => (d.source === id || d.target === id)
                                    ? 0.95 : Math.min(baseOp, 0.05))
      .attr('stroke', d => d.source === id ? '#58a6ff' : d.target === id ? '#3fb950' : '#6b7583')
      .attr('stroke-width', d => (d.source === id || d.target === id) ? 1.8 : 1)
      .attr('marker-end', d => d.source === id ? 'url(#est-arrow-o)'
                            : d.target === id ? 'url(#est-arrow-i)'
                            : mostrar ? 'url(#est-arrow)' : null)
      .raise();
    lSel.style('opacity', d => vecinos.has(d.id) ? 1 : 0.25);
    gSel.style('opacity', 0.75);
  }

  function estClear() {
    ePath.attr('stroke-opacity', baseOp).attr('stroke', '#6b7583')
         .attr('stroke-width', 1)
         .attr('marker-end', mostrar ? 'url(#est-arrow)' : null);
    lSel.style('opacity', 1);
    gSel.style('opacity', 1);
  }

  let fijado = null;
  lSel.on('mouseenter', (ev, d) => { if (!fijado) estFocus(d.id); })
      .on('mouseleave', ()      => { if (!fijado) estClear(); })
      .on('click', (ev, d) => {
        ev.stopPropagation();
        fijado = d.id;
        estFocus(d.id);
        const nd = fuente.nodo(d);
        if (!nd) return;
        navHistory = [{ id: d.id, label: nd.label }];
        renderBreadcrumb();
        renderPanelFor(nd);
        // Un endpoint ya sabe qué función lo atiende: la referencia sale con
        // el rango de líneas sin que haya que elegir un chip a mano.
        if (nd.fn) { _sub = { kind: 'fn', name: nd.fn }; actualizarPreview(); }
        elPanel.classList.add('open');
      });

  svg.on('click', () => { fijado = null; estClear(); elPanel.classList.remove('open'); });

  window._focusNode  = (id) => { if (_estIndex[id]) { fijado = id; estFocus(id); } };
  window._applyFocus = estFocus;
  window._clearFocus = estClear;

  // ── encuadre ──
  const pad   = 40;
  const scale = Math.min((W - pad * 2) / root.w, (H - pad * 2) / root.h, 1.6);
  const tx    = (W - root.w * scale) / 2;
  const ty    = (H - root.h * scale) / 2;
  svg.call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));

  elHint.textContent = fuente.hint(edges.length, mostrar);
}

/** Curva suave entre dos cajas, saliendo por el borde más cercano. */
function _estEdgePath(s, t) {
  const dx = t.cx - s.cx, dy = t.cy - s.cy;
  const dist = Math.hypot(dx, dy) || 1;

  // Punto de salida y de llegada sobre el borde de cada caja
  const [sx, sy] = _estBorde(s, dx, dy);
  const [tx, ty] = _estBorde(t, -dx, -dy);

  // Curvatura proporcional a la distancia, perpendicular al tramo
  const k  = Math.min(dist * 0.16, 55);
  const mx = (sx + tx) / 2 - (ty - sy) / dist * k;
  const my = (sy + ty) / 2 + (tx - sx) / dist * k;
  return `M${sx},${sy} Q${mx},${my} ${tx},${ty}`;
}

function _estBorde(box, dx, dy) {
  const hw = box.w / 2, hh = box.h / 2;
  if (!dx && !dy) return [box.cx, box.cy];
  const escala = Math.min(
    dx ? hw / Math.abs(dx) : Infinity,
    dy ? hh / Math.abs(dy) : Infinity,
  );
  return [box.cx + dx * escala, box.cy + dy * escala];
}
