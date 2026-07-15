const PID = document.body.dataset.pid;
const MODE = document.body.dataset.mode;
const IS_VIDEO = MODE === 'video';
let STATE = null;
let mediaBust = Date.now();  // cambia solo tras una acción del usuario (regen de fichas)

const $ = s => document.querySelector(s);
const esc = t => (t || '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fileUrl = p => `/files/${PID}/${(p || '').replace(/\\/g, '/').split(`projects/${PID}/`).pop()}`;
const last = arr => arr[arr.length - 1];
const activeAssets = (sc, kind) => (sc.assets || []).filter(a => a.kind === kind && a.active);
const preview = (t, n = 55) => { t = (t || '').trim(); return (esc(t.slice(0, n)) + (t.length > n ? '…' : '')) || '<i>vacío</i>'; };

// Escribe innerHTML SOLO si cambió: los <video>/<audio> en reproducción no se recrean.
function setHTML(el, html) {
  if (!el || el.__html === html) return false;
  el.__html = html;
  el.innerHTML = html;
  return true;
}

// congela un contenedor mientras el usuario escribe dentro (evita que el polling le borre lo tecleado)
function attachEditingGuard(el) {
  if (!el || el.__guarded) return;
  el.__guarded = true;
  el.addEventListener('focusin', () => el.__editing = true);
  el.addEventListener('focusout', () => setTimeout(() => el.__editing = false, 250));
}

// <select> reutilizable con los modelos disponibles para una tarea (image/video/tts/music/storyboard)
function modelSelect(task) {
  const models = TASKS[task] || {};
  const def = DEFAULTS[task] || '';
  const opts = Object.entries(models).map(([mid, m]) =>
    `<option value="${mid}" ${mid === def ? 'selected' : ''}>${esc(m.label)}</option>`).join('');
  return `<select class="modelsel" data-task="${task}">${opts}</select>`;
}

async function api(path, body) {
  const r = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
  const d = await r.json().catch(() => ({}));
  if (!r.ok) alert(d.detail || d.error || 'Error');
  mediaBust = Date.now();
  refresh();
  return d;
}

async function apiDelete(path) {
  if (!confirm('¿Borrar definitivamente? No se puede deshacer.')) return;
  const r = await fetch(path, {method: 'DELETE'});
  const d = await r.json().catch(() => ({}));
  if (!r.ok) alert(d.detail || d.error || 'Error');
  mediaBust = Date.now();
  refresh();
}

async function uploadRef(entity, id, file) {
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch(`/api/bible/${entity}/${id}/upload_ref`, {method: 'POST', body: fd});
  const d = await r.json().catch(() => ({}));
  if (!r.ok) alert(d.detail || d.error || 'Error');
  mediaBust = Date.now();
  refresh();
}

if (!IS_VIDEO) document.querySelectorAll('.video-only').forEach(e => e.remove());

// --- menú lateral: cambia de sección sin recargar ---
document.querySelectorAll('.navbtn').forEach(b => b.onclick = () => {
  document.querySelectorAll('.navbtn').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
  b.classList.add('active');
  const v = document.querySelector(`.view[data-view="${b.dataset.view}"]`);
  if (v) v.classList.remove('hidden');
});

// selector de modelo para "Generar imágenes" (una sola vez: no depende del estado)
if ($('#imagesModelWrap')) $('#imagesModelWrap').innerHTML = modelSelect('image');

// --- acciones globales (botones de la barra superior / secciones) ---
document.querySelectorAll('[data-act]').forEach(b => {
  b.onclick = () => api(`/api/project/${PID}/${b.dataset.act}`);
});
if ($('#imagesBtn')) $('#imagesBtn').onclick = () => {
  const model = $('#imagesModelWrap .modelsel').value;
  api(`/api/project/${PID}/images`, {model});
};
if ($('#animateBtn')) $('#animateBtn').onclick = async () => {
  let est = await (await fetch(`/api/project/${PID}/estimate_video`)).json();
  if (!est.scenes) {  // nada aprobado aún: ofrecer aprobar todas y generar
    if (!confirm('No hay escenas aprobadas. ¿Aprobar todas y generar sus vídeos?')) return;
    await fetch(`/api/project/${PID}/approve_all`, {method: 'POST'});
    est = await (await fetch(`/api/project/${PID}/estimate_video`)).json();
  }
  if (confirm(`Se generarán los vídeos de ${est.scenes} escenas (${est.seconds}s) en ${est.formats.join(' y ')} con ${est.model}.\nCoste estimado: $${est.usd.toFixed(2)}. Los clips tardan 1-5 min cada uno. ¿Continuar?`))
    api(`/api/project/${PID}/animate`);
};

// editar dentro de una tarjeta de escena congela SOLO esa tarjeta (no se re-renderiza mientras escribes)
$('#sceneCards').addEventListener('focusin', e => { const s = e.target.closest('[data-slot]'); if (s) s.__editing = true; });
$('#sceneCards').addEventListener('focusout', e => { const s = e.target.closest('[data-slot]'); if (s) setTimeout(() => s.__editing = false, 250); });

// ---------- render ----------

function render() {
  const s = STATE;
  $('#cost').textContent = '$' + s.project.cost_total.toFixed(4);
  $('#ptitle').textContent = s.project.title;
  $('#statusmsg').textContent = s.project.status_msg || '';
  $('#spinner').classList.toggle('hidden', !s.project.busy);
  // los botones de navegación deben poder pulsarse aunque haya un job en marcha
  document.querySelectorAll('button:not(.navbtn)').forEach(b => b.disabled = !!s.project.busy);
  $('#toast').classList.toggle('hidden', !s.project.busy);
  $('#toastmsg').textContent = s.project.status_msg || 'Trabajando…';

  const scriptEl = $('#scripttext');
  if (scriptEl) scriptEl.textContent = s.project.script || '';

  renderCharacters(s);
  renderLocations(s);
  renderProps(s);
  renderVoices(s);
  renderProgress(s);
  renderScenes(s);
  renderFinals(s);
  setHTML($('#costtable tbody'), s.costs.map(c =>
    `<tr><td>${esc(c.model)}</td><td>${esc(c.units)}</td><td>$${c.usd.toFixed(4)}</td></tr>`).join(''));
}

// ---------- biblias: personajes, localizaciones, objetos, voces ----------
// Ficha genérica reutilizada por character/location/prop (todas tienen imagen de referencia).

function bibleThumb(e) {
  return e.ref_image ? `<img src="${fileUrl(e.ref_image)}?v=${mediaBust}">` : '<div class="ph">sin imagen</div>';
}

function bibleCardHTML(entity, e, extraHTML) {
  return `<div class="char" data-card="${entity}:${e.id}">
      ${bibleThumb(e)}
      <input data-f="name" value="${esc(e.name)}" placeholder="nombre">
      <textarea data-f="description" rows="3" placeholder="descripción">${esc(e.description)}</textarea>
      ${extraHTML || ''}
      <span class="badge ${e.approved ? 'ok' : ''}">${e.approved ? '✅ aprobado' : 'borrador'}</span>
      <div class="row">
        <button class="mini" data-bsave="${entity}:${e.id}">💾 Guardar</button>
        <button class="mini" data-bapprove="${entity}:${e.id}">✅ Aprobar</button>
        <button class="mini danger" data-bdel="${entity}:${e.id}">🗑️ Borrar</button>
      </div>
      <div class="row">
        ${modelSelect('image')}
        <button class="mini" data-bgenref="${entity}:${e.id}">🎨 Generar ref.</button>
      </div>
      <label class="mini upl">📤 Subir imagen<input type="file" accept="image/*" class="hidden" data-bupload="${entity}:${e.id}"></label>
    </div>`;
}

// bloque "crear nuevo": prompt (IA rellena ficha, opcionalmente genera imagen) + alternativa manual
function createBlockHTML(entity, label, manualExtraHTML) {
  return `<div class="bcreate">
    <label>Crear ${label} por prompt (la IA rellena la ficha)
      <textarea data-newprompt rows="2" placeholder="Describe brevemente el/la ${label}..."></textarea>
    </label>
    <div class="row">
      ${modelSelect('image')}
      <label class="chk"><input type="checkbox" data-newgenimg checked> generar imagen</label>
      <button class="mini primary" data-createprompt="${entity}">✨ Crear por prompt</button>
    </div>
    <details><summary>o crear manual (sin IA)</summary>
      <div class="grow">
        <label>Nombre<input data-newf="${entity}:name"></label>
        ${manualExtraHTML || ''}
        <button class="mini" data-createmanual="${entity}">➕ Crear manual</button>
      </div>
    </details>
  </div>`;
}

function bindCreateBlock(container, entity) {
  container.querySelectorAll(`[data-createprompt="${entity}"]`).forEach(b => b.onclick = () => {
    const wrap = b.closest('.bcreate');
    const prompt = wrap.querySelector('[data-newprompt]').value.trim();
    if (!prompt) return alert('Escribe una descripción');
    const model = wrap.querySelector('.modelsel').value;
    const gen_image = wrap.querySelector('[data-newgenimg]').checked;
    api(`/api/project/${PID}/bible/${entity}`, {prompt, gen_image, model});
    wrap.querySelector('[data-newprompt]').value = '';
  });
  container.querySelectorAll(`[data-createmanual="${entity}"]`).forEach(b => b.onclick = () => {
    const wrap = b.closest('.bcreate');
    const body = {};
    wrap.querySelectorAll(`[data-newf^="${entity}:"]`).forEach(f => {
      let v = f.value;
      const key = f.dataset.newf.split(':')[1];
      if (key === 'owner_character_id' && v === '') v = null;
      body[key] = v;
    });
    api(`/api/project/${PID}/bible/${entity}`, body);
  });
}

function bindBibleCards(container, entity) {
  container.querySelectorAll(`[data-bsave^="${entity}:"]`).forEach(b => b.onclick = () => {
    const [ent, id] = b.dataset.bsave.split(':');
    const card = container.querySelector(`[data-card="${ent}:${id}"]`);
    const body = {};
    card.querySelectorAll('[data-f]').forEach(f => {
      let v = f.value;
      if (f.dataset.f === 'owner_character_id' && v === '') v = null;
      body[f.dataset.f] = v;
    });
    api(`/api/bible/${ent}/${id}/update`, body);
  });
  container.querySelectorAll(`[data-bapprove^="${entity}:"]`).forEach(b => b.onclick = () => {
    const [ent, id] = b.dataset.bapprove.split(':');
    api(`/api/bible/${ent}/${id}/approve`);
  });
  container.querySelectorAll(`[data-bgenref^="${entity}:"]`).forEach(b => b.onclick = () => {
    const [ent, id] = b.dataset.bgenref.split(':');
    const model = b.closest('.char').querySelector('.modelsel').value;
    api(`/api/bible/${ent}/${id}/gen_ref`, {model});
  });
  container.querySelectorAll(`[data-bupload^="${entity}:"]`).forEach(inp => inp.onchange = () => {
    const [ent, id] = inp.dataset.bupload.split(':');
    if (inp.files[0]) uploadRef(ent, id, inp.files[0]);
  });
  container.querySelectorAll(`[data-bdel^="${entity}:"]`).forEach(b => b.onclick = () => {
    const [ent, id] = b.dataset.bdel.split(':');
    apiDelete(`/api/bible/${ent}/${id}`);
  });
}

function renderCharacters(s) {
  const el = $('#characters');
  if (!el || el.__editing) return;
  const extra = c => `
    <label class="mini">Género
      <select data-f="gender">
        <option value="" ${!c.gender ? 'selected' : ''}>—</option>
        <option value="hombre" ${c.gender === 'hombre' ? 'selected' : ''}>hombre</option>
        <option value="mujer" ${c.gender === 'mujer' ? 'selected' : ''}>mujer</option>
      </select></label>
    ${IS_VIDEO ? `<label class="mini">🎙️ Voz TTS
      <select data-voice-cid="${c.id}">${VOICES.map(v => `<option ${v === c.voice ? 'selected' : ''}>${v}</option>`).join('')}</select></label>` : ''}
    <button class="mini" data-regen-char="${c.id}">🔄 Regenerar ficha (rápido)</button>`;
  const manualExtra = `<label>Género
    <select data-newf="character:gender"><option value="">—</option><option value="hombre">hombre</option><option value="mujer">mujer</option></select></label>`;
  const html = createBlockHTML('character', 'personaje', manualExtra) +
    `<div class="chargrid">${s.characters.map(c => bibleCardHTML('character', c, extra(c))).join('') ||
      '<span class="muted">Aún no hay personajes. Genera el storyboard o crea uno por prompt.</span>'}</div>`;
  if (!setHTML(el, html)) return;
  attachEditingGuard(el);
  bindCreateBlock(el, 'character');
  bindBibleCards(el, 'character');
  el.querySelectorAll('[data-voice-cid]').forEach(sel => sel.onchange = () =>
    api(`/api/character/${sel.dataset.voiceCid}/voice`, {voice: sel.value}));
  el.querySelectorAll('[data-regen-char]').forEach(b => b.onclick = () => {
    const desc = el.querySelector(`[data-card="character:${b.dataset.regenChar}"] [data-f="description"]`).value;
    api(`/api/character/${b.dataset.regenChar}/regen`, {description: desc});
  });
}

function renderLocations(s) {
  const el = $('#locations');
  if (!el || el.__editing) return;
  const extra = l => `<label class="mini">Tipo
    <input list="loctypes" data-f="type" value="${esc(l.type)}" placeholder="interior/exterior"></label>`;
  const manualExtra = `<label>Tipo<input list="loctypes" data-newf="location:type" placeholder="interior/exterior"></label>`;
  const html = `<datalist id="loctypes"><option value="interior"><option value="exterior"></datalist>` +
    createBlockHTML('location', 'localización', manualExtra) +
    `<div class="chargrid">${s.locations.map(l => bibleCardHTML('location', l, extra(l))).join('') ||
      '<span class="muted">Aún no hay localizaciones.</span>'}</div>`;
  if (!setHTML(el, html)) return;
  attachEditingGuard(el);
  bindCreateBlock(el, 'location');
  bindBibleCards(el, 'location');
}

function renderProps(s) {
  const el = $('#props');
  if (!el || el.__editing) return;
  const cats = ['objeto', 'vehiculo', 'vestuario', 'accesorio', 'mascota'];
  const ownerOpts = owner => '<option value="">— sin dueño —</option>' +
    s.characters.map(c => `<option value="${c.id}" ${owner == c.id ? 'selected' : ''}>${esc(c.name)}</option>`).join('');
  const extra = p => `
    <label class="mini">Categoría
      <select data-f="category">${cats.map(c => `<option ${c === p.category ? 'selected' : ''}>${c}</option>`).join('')}</select></label>
    <label class="mini">Dueño
      <select data-f="owner_character_id">${ownerOpts(p.owner_character_id)}</select></label>`;
  const manualExtra = `<label>Categoría<select data-newf="prop:category">${cats.map(c => `<option>${c}</option>`).join('')}</select></label>
    <label>Dueño<select data-newf="prop:owner_character_id">${ownerOpts(null)}</select></label>`;
  const html = createBlockHTML('prop', 'objeto/vestuario', manualExtra) +
    `<div class="chargrid">${s.props.map(p => bibleCardHTML('prop', p, extra(p))).join('') ||
      '<span class="muted">Aún no hay objetos ni vestuario.</span>'}</div>`;
  if (!setHTML(el, html)) return;
  attachEditingGuard(el);
  bindCreateBlock(el, 'prop');
  bindBibleCards(el, 'prop');
}

function renderVoices(s) {
  const el = $('#voices');
  if (!el || el.__editing) return;
  const manual = `<div class="bcreate">
    <div class="grow">
      <label>Nombre<input data-newf="voice:name"></label>
      <label>Voz base<select data-newf="voice:base_voice">${VOICES.map(v => `<option>${v}</option>`).join('')}</select></label>
    </div>
    <label>Instrucción de tono/ritmo<textarea data-newf="voice:instruction" rows="2" placeholder="ej: voz grave, ritmo pausado, tono cálido"></textarea></label>
    <button class="mini primary" data-createmanual="voice">➕ Crear voz</button>
  </div>`;
  const cards = s.voices.map(v => `
    <div class="char" data-card="voice:${v.id}">
      <input data-f="name" value="${esc(v.name)}" placeholder="nombre de la voz">
      <label class="mini">Voz base
        <select data-f="base_voice">${VOICES.map(b => `<option ${b === v.base_voice ? 'selected' : ''}>${b}</option>`).join('')}</select></label>
      <label class="mini">Instrucción (tono/ritmo)
        <textarea data-f="instruction" rows="2">${esc(v.instruction)}</textarea></label>
      ${v.sample_path ? `<audio controls src="${fileUrl(v.sample_path)}?v=${mediaBust}"></audio>` : '<span class="muted">sin muestra aún</span>'}
      <span class="badge ${v.approved ? 'ok' : ''}">${v.approved ? '✅ aprobado' : 'borrador'}</span>
      <div class="row">
        <button class="mini" data-bsave="voice:${v.id}">💾 Guardar</button>
        <button class="mini" data-bapprove="voice:${v.id}">✅ Aprobar</button>
        <button class="mini danger" data-bdel="voice:${v.id}">🗑️ Borrar</button>
      </div>
      <input placeholder="Texto de prueba (opcional)" data-vsampletext>
      <div class="row">
        ${modelSelect('tts')}
        <button class="mini" data-vsample="${v.id}">🔊 Probar voz</button>
      </div>
    </div>`).join('') || '<span class="muted">Aún no hay voces en el stock.</span>';
  const html = manual + `<div class="chargrid">${cards}</div>`;
  if (!setHTML(el, html)) return;
  attachEditingGuard(el);
  bindCreateBlock(el, 'voice');   // solo hay bloque manual: no existe data-createprompt="voice" (no-op si no lo encuentra)
  bindBibleCards(el, 'voice');    // gen_ref/upload no aplican a voces: sus selectores no encuentran nada (no-op)
  el.querySelectorAll('[data-vsample]').forEach(b => b.onclick = () => {
    const card = b.closest('.char');
    const text = (card.querySelector('[data-vsampletext]') || {}).value || '';
    const model = card.querySelector('.modelsel').value;
    api(`/api/bible/voice/${b.dataset.vsample}/sample`, {text, model});
  });
}

function renderProgress(s) {
  const targets = document.querySelectorAll('.progressSlot');
  if (!targets.length) return;
  const msg = (s.project.status_msg || '').toLowerCase();
  let doneFn = null, label = '';
  if (s.project.busy && /imagen|imágenes/.test(msg)) { label = 'Imágenes'; doneFn = sc => activeAssets(sc, IS_VIDEO ? 'keyframe_first' : 'slide').length; }
  else if (s.project.busy && /voz|audio/.test(msg)) { label = 'Voces'; doneFn = sc => activeAssets(sc, 'voice').length; }
  else if (s.project.busy && /anim|clip/.test(msg)) { label = 'Clips'; doneFn = sc => activeAssets(sc, 'preview').length || activeAssets(sc, 'clip').length; }
  if (!doneFn) { targets.forEach(el => setHTML(el, '')); return; }
  const cur = parseInt((msg.match(/escena (\d+)/) || [])[1] || 0);
  const done = s.scenes.filter(doneFn).length, total = s.scenes.length || 1;
  const html = `<div class="pline"><span>${label}: ${done}/${total}</span>
      <div class="pbar"><div class="pfill" style="width:${Math.round(done / total * 100)}%"></div></div></div>
    <div class="chips">${s.scenes.map(sc =>
      `<span class="chip ${doneFn(sc) ? 'done' : cur === sc.ord + 1 ? 'doing' : ''}">${doneFn(sc) ? '✅' : cur === sc.ord + 1 ? '⏳' : '○'} E${sc.ord + 1}</span>`).join('')}</div>`;
  targets.forEach(el => setHTML(el, html));
}

function renderScenes(s) {
  const cont = $('#sceneCards');
  const ids = s.scenes.map(sc => sc.id).join(',');
  if (cont.__ids !== ids) {  // (re)crear un hueco por escena solo si cambia la lista
    cont.__ids = ids;
    cont.innerHTML = s.scenes.map(sc => `<section class="card scenecard" data-slot="${sc.id}"></section>`).join('')
      || '<section class="card"><span class="muted">Aún no hay escenas. Genera el storyboard.</span></section>';
  }
  s.scenes.forEach(sc => {
    const slot = cont.querySelector(`[data-slot="${sc.id}"]`);
    if (!slot || slot.__editing) return;
    if (setHTML(slot, sceneCardHTML(sc, s))) bindSceneCard(slot, sc, s);
  });
}

function sceneCardHTML(sc, s) {
  const imgKind = IS_VIDEO ? 'keyframe_first' : 'slide';
  const kf = last(activeAssets(sc, imgKind));
  const voice = last(activeAssets(sc, 'voice'));
  const media = last(activeAssets(sc, 'preview')) || last(activeAssets(sc, 'clip'));

  const guion = `<div class="stage">
      <div class="stagelabel">📝 Guión</div>
      <div class="gfields">
        <details class="gfield"><summary><b>Visual</b> <span class="fpreview">${preview(sc.visual)}</span></summary>
          <textarea data-sid="${sc.id}" data-f="visual" rows="4">${esc(sc.visual)}</textarea></details>
        <details class="gfield"><summary><b>Diálogo / Texto</b> <span class="fpreview">${preview(sc.dialogue)}</span></summary>
          <textarea data-sid="${sc.id}" data-f="dialogue" rows="3">${esc(sc.dialogue)}</textarea></details>
        <div class="grow">
          <label>Cámara<input data-sid="${sc.id}" data-f="camera" value="${esc(sc.camera)}"></label>
          <label class="short">seg<input data-sid="${sc.id}" data-f="duration_s" value="${sc.duration_s}"></label>
          <button class="mini" data-save="${sc.id}">💾 Guardar guión</button>
        </div>
      </div>
    </div>`;

  const imagen = `<div class="stage">
      <div class="stagelabel">🖼️ Imagen</div>
      ${kf ? `<img class="stagemedia" src="${fileUrl(kf.path)}?v=${kf.id}">` : '<span class="muted">sin imagen — pulsa "Generar imágenes" en Storyboard</span>'}
      <div class="row">
        <input placeholder="Correcciones (ej: la camisa debe ser roja)" data-fb="${sc.id}">
      </div>
      <div class="row">
        ${modelSelect('image')}
        <button class="mini" data-regen="${sc.id}">🔄 Regenerar</button>
        <button class="mini" data-approve="${sc.id}">✅ Aprobar</button>
      </div>
    </div>`;

  const audio = `<div class="stage">
      <div class="stagelabel">🎙️ Audio</div>
      ${voice ? `<audio controls src="${fileUrl(voice.path)}?v=${voice.id}"></audio>` : '<span class="muted">sin voz — pulsa "Voz + música" en Animación</span>'}
      <div class="row">
        <input placeholder="Ajuste de voz (ej: más lento y enfadado)" data-afb="${sc.id}">
        <button class="mini" data-reedit-voice="${sc.id}">🎙️ Reeditar voz</button>
      </div>
    </div>`;

  const video = `<div class="stage">
      <div class="stagelabel">🎬 Vídeo ${media && media.kind === 'preview' ? '<span class="ok-badge">🔊 con audio</span>' : ''}</div>
      ${media ? `<video class="stagemedia" controls preload="metadata" src="${fileUrl(media.path)}?v=${media.id}"></video>`
              : '<span class="muted">sin vídeo — pulsa "Generar vídeos" en Animación</span>'}
      <div class="row">
        <input placeholder="Mejora del vídeo (ej: más movimiento de cámara)" data-vfb="${sc.id}">
        <button class="mini" data-reedit-video="${sc.id}">🎬 Reeditar vídeo</button>
      </div>
    </div>`;

  const charIds = JSON.parse(sc.char_ids || '[]');
  const propIds = JSON.parse(sc.prop_ids || '[]');
  const vinculos = `<div class="stage">
      <div class="stagelabel">🔗 Vínculos con la biblia</div>
      <label class="mini">Personajes presentes
        <select multiple size="4" data-lf="char_ids">${(s.characters || []).map(c =>
          `<option value="${c.id}" ${charIds.includes(c.id) ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select></label>
      <label class="mini">Localización
        <select data-lf="location_id"><option value="">— ninguna —</option>${(s.locations || []).map(l =>
          `<option value="${l.id}" ${sc.location_id == l.id ? 'selected' : ''}>${esc(l.name)}</option>`).join('')}</select></label>
      <label class="mini">Objetos/vestuario
        <select multiple size="4" data-lf="prop_ids">${(s.props || []).map(p =>
          `<option value="${p.id}" ${propIds.includes(p.id) ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></label>
      <button class="mini" data-savelink="${sc.id}">🔗 Guardar vínculos</button>
    </div>`;

  const edicion = `<div class="stage">
      <div class="stagelabel">🪄 Editar imagen por instrucción</div>
      <span class="muted">Mantiene la identidad de la imagen actual y aplica el cambio descrito.</span>
      <input placeholder="Ej: cambia el fondo a de noche" data-editimg="${sc.id}">
      <div class="row">
        ${modelSelect('image')}
        <button class="mini" data-doeditimg="${sc.id}">🪄 Aplicar edición</button>
      </div>
    </div>`;

  const sceneCost = (sc.assets || []).reduce((a, x) => a + (x.cost || 0), 0);
  const versiones = `<div class="stage">
      <div class="stagelabel">💰 Versiones y coste (escena: $${sceneCost.toFixed(4)})</div>
      <table class="scenetable"><thead><tr><th>Tipo</th><th>Fmt</th><th>#</th><th>Activo</th><th>USD</th></tr></thead>
        <tbody>${(sc.assets || []).map(a =>
          `<tr class="${a.active ? '' : 'inactive'}"><td>${esc(a.kind)}</td><td>${esc(a.format)}</td><td>v${a.gen_n}</td><td>${a.active ? '✅' : ''}</td><td>$${(a.cost || 0).toFixed(4)}</td></tr>`
        ).join('') || '<tr><td colspan="5" class="muted">sin assets aún</td></tr>'}</tbody></table>
    </div>`;

  return `<div class="scenehead"><strong>Escena ${sc.ord + 1}</strong>
      <span class="badge ${sc.approved ? 'ok' : ''}">${sc.approved ? '✅ aprobada' : 'pendiente'}</span></div>
    <div class="stages">${guion}${imagen}${IS_VIDEO ? audio + video : ''}${vinculos}${edicion}${versiones}</div>`;
}

function bindSceneCard(slot, sc, s) {
  const val = sel => (slot.querySelector(sel) || {}).value || '';
  slot.querySelectorAll('[data-save]').forEach(b => b.onclick = () => {
    const body = {};
    slot.querySelectorAll(`[data-sid="${b.dataset.save}"]`).forEach(e =>
      body[e.dataset.f] = e.dataset.f === 'duration_s' ? parseFloat(e.value) : e.value);
    api(`/api/scene/${b.dataset.save}/update`, body);
  });
  slot.querySelectorAll('[data-regen]').forEach(b => b.onclick = () => {
    const model = b.closest('.stage').querySelector('.modelsel').value;
    api(`/api/scene/${b.dataset.regen}/regen`, {feedback: val(`[data-fb="${b.dataset.regen}"]`), model});
  });
  slot.querySelectorAll('[data-approve]').forEach(b => b.onclick = () =>
    api(`/api/scene/${b.dataset.approve}/approve`));
  slot.querySelectorAll('[data-reedit-voice]').forEach(b => b.onclick = () =>
    api(`/api/scene/${b.dataset.reeditVoice}/reedit_voice`, {prompt: val(`[data-afb="${b.dataset.reeditVoice}"]`)}));
  slot.querySelectorAll('[data-reedit-video]').forEach(b => b.onclick = () => {
    if (confirm('Reeditar regenerará el clip con Veo (coste ~$0.15/seg del clip). ¿Continuar?'))
      api(`/api/scene/${b.dataset.reeditVideo}/reedit_video`, {prompt: val(`[data-vfb="${b.dataset.reeditVideo}"]`)});
  });
  slot.querySelectorAll('[data-savelink]').forEach(b => b.onclick = () => {
    const stage = b.closest('.stage');
    const char_ids = [...stage.querySelector('[data-lf="char_ids"]').selectedOptions].map(o => +o.value);
    const prop_ids = [...stage.querySelector('[data-lf="prop_ids"]').selectedOptions].map(o => +o.value);
    const locv = stage.querySelector('[data-lf="location_id"]').value;
    api(`/api/scene/${b.dataset.savelink}/link`, {char_ids, prop_ids, location_id: locv ? +locv : null});
  });
  slot.querySelectorAll('[data-doeditimg]').forEach(b => b.onclick = () => {
    const stage = b.closest('.stage');
    const instruction = stage.querySelector('[data-editimg]').value.trim();
    if (!instruction) return alert('Escribe una instrucción de edición');
    const model = stage.querySelector('.modelsel').value;
    api(`/api/scene/${b.dataset.doeditimg}/edit_image`, {instruction, model});
  });
}

function renderFinals(s) {
  setHTML($('#finals'), s.project_assets.filter(a => a.kind === 'final').map(a => {
    const name = a.path.split(/[\\/]/).pop();
    const url = fileUrl(a.path);
    const when = a.created ? new Date(a.created * 1000).toLocaleTimeString() : '';
    if (name.endsWith('.mp4')) return `<figure class="clip"><video controls preload="metadata" src="${url}?v=${a.id}"></video><figcaption><a href="${url}" download>${name}</a><br><span class="muted">generado ${when}</span></figcaption></figure>`;
    return `<div class="dl"><a href="${url}" download>⬇️ ${name}</a> <span class="muted">(${when})</span></div>`;
  }).join('') || '<span class="muted">aún no hay entregables</span>');
}

async function refresh() {
  try {
    STATE = await (await fetch(`/api/project/${PID}/state`)).json();
    render();
  } catch (e) { /* servidor reiniciándose */ }
}

refresh();
setInterval(refresh, 3000);
