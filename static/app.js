const PID = document.body.dataset.pid;
const MODE = document.body.dataset.mode;
const IS_VIDEO = MODE === 'video';
let STATE = null;
let mediaBust = Date.now();  // cambia solo tras una acción del usuario (regen de fichas)

const $ = s => document.querySelector(s);
const esc = t => (t || '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fileUrl = p => `/files/${PID}/${p.replace(/\\/g, '/').split(`projects/${PID}/`).pop()}`;
const last = arr => arr[arr.length - 1];
const activeAssets = (sc, kind) => (sc.assets || []).filter(a => a.kind === kind && a.active);

// Escribe innerHTML SOLO si cambió: los <video>/<audio> en reproducción no se recrean.
function setHTML(el, html) {
  if (!el || el.__html === html) return false;
  el.__html = html;
  el.innerHTML = html;
  return true;
}

async function api(path, body) {
  const r = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
  const d = await r.json().catch(() => ({}));
  if (!r.ok) alert(d.detail || d.error || 'Error');
  mediaBust = Date.now();
  refresh();
  return d;
}

if (!IS_VIDEO) document.querySelectorAll('.video-only').forEach(e => e.remove());

// --- acciones globales (botones de la barra superior) ---
document.querySelectorAll('[data-act]').forEach(b => {
  b.onclick = () => api(`/api/project/${PID}/${b.dataset.act}`);
});
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
  $('#cost').textContent = '$' + s.project.cost_total.toFixed(2);
  $('#ptitle').textContent = s.project.title;
  $('#statusmsg').textContent = s.project.status_msg || '';
  $('#spinner').classList.toggle('hidden', !s.project.busy);
  document.querySelectorAll('button').forEach(b => b.disabled = !!s.project.busy);
  $('#toast').classList.toggle('hidden', !s.project.busy);
  $('#toastmsg').textContent = s.project.status_msg || 'Trabajando…';

  renderCharacters(s);
  renderProgress(s);
  renderScenes(s);
  renderFinals(s);
  setHTML($('#costtable tbody'), s.costs.map(c =>
    `<tr><td>${esc(c.model)}</td><td>${esc(c.units)}</td><td>$${c.usd.toFixed(4)}</td></tr>`).join(''));
}

function renderCharacters(s) {
  const el = $('#characters');
  if (el.__editing) return;
  const html = s.characters.map(c => `
    <div class="char">
      ${c.ref_image ? `<img src="/files/${PID}/${c.ref_image}?v=${mediaBust}">` : '<div class="ph">sin ficha</div>'}
      <strong>${esc(c.name)} ${c.gender ? `<span class="muted">(${esc(c.gender)})</span>` : ''}</strong>
      ${IS_VIDEO ? `<label class="mini">🎙️ Voz
        <select data-voice-cid="${c.id}">${VOICES.map(v => `<option ${v === c.voice ? 'selected' : ''}>${v}</option>`).join('')}</select></label>` : ''}
      <textarea data-cid="${c.id}" class="chardesc" rows="3">${esc(c.description)}</textarea>
      <button class="mini" data-regen-char="${c.id}">🔄 Regenerar ficha</button>
    </div>`).join('') || '<span class="muted">Genera el storyboard para crear los personajes.</span>';
  if (!setHTML(el, html)) return;
  el.addEventListener('focusin', () => el.__editing = true, {once: false});
  el.addEventListener('focusout', () => setTimeout(() => el.__editing = false, 250), {once: false});
  el.querySelectorAll('[data-voice-cid]').forEach(sel => sel.onchange = () =>
    api(`/api/character/${sel.dataset.voiceCid}/voice`, {voice: sel.value}));
  el.querySelectorAll('[data-regen-char]').forEach(b => b.onclick = () =>
    api(`/api/character/${b.dataset.regenChar}/regen`, {description: el.querySelector(`.chardesc[data-cid="${b.dataset.regenChar}"]`).value}));
}

function renderProgress(s) {
  const el = $('#globalprog');
  const msg = (s.project.status_msg || '').toLowerCase();
  let doneFn = null, label = '';
  if (s.project.busy && /imagen|imágenes/.test(msg)) { label = 'Imágenes'; doneFn = sc => activeAssets(sc, IS_VIDEO ? 'keyframe_first' : 'slide').length; }
  else if (s.project.busy && /voz|audio/.test(msg)) { label = 'Voces'; doneFn = sc => activeAssets(sc, 'voice').length; }
  else if (s.project.busy && /anim|clip/.test(msg)) { label = 'Clips'; doneFn = sc => activeAssets(sc, 'preview').length || activeAssets(sc, 'clip').length; }
  if (!doneFn) return setHTML(el, '');
  const cur = parseInt((msg.match(/escena (\d+)/) || [])[1] || 0);
  const done = s.scenes.filter(doneFn).length, total = s.scenes.length || 1;
  setHTML(el, `<div class="pline"><span>${label}: ${done}/${total}</span>
      <div class="pbar"><div class="pfill" style="width:${Math.round(done / total * 100)}%"></div></div></div>
    <div class="chips">${s.scenes.map(sc =>
      `<span class="chip ${doneFn(sc) ? 'done' : cur === sc.ord + 1 ? 'doing' : ''}">${doneFn(sc) ? '✅' : cur === sc.ord + 1 ? '⏳' : '○'} E${sc.ord + 1}</span>`).join('')}</div>`);
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
    if (setHTML(slot, sceneCardHTML(sc))) bindSceneCard(slot, sc);
  });
}

function sceneCardHTML(sc) {
  const imgKind = IS_VIDEO ? 'keyframe_first' : 'slide';
  const kf = last(activeAssets(sc, imgKind));
  const voice = last(activeAssets(sc, 'voice'));
  const media = last(activeAssets(sc, 'preview')) || last(activeAssets(sc, 'clip'));

  const guion = `<div class="stage">
      <div class="stagelabel">📝 Guión</div>
      <div class="gfields">
        <label>Visual<textarea data-sid="${sc.id}" data-f="visual" rows="2">${esc(sc.visual)}</textarea></label>
        <label>Diálogo / Texto<textarea data-sid="${sc.id}" data-f="dialogue" rows="2">${esc(sc.dialogue)}</textarea></label>
        <div class="grow">
          <label>Cámara<input data-sid="${sc.id}" data-f="camera" value="${esc(sc.camera)}"></label>
          <label class="short">seg<input data-sid="${sc.id}" data-f="duration_s" value="${sc.duration_s}"></label>
          <button class="mini" data-save="${sc.id}">💾 Guardar guión</button>
        </div>
      </div>
    </div>`;

  const imagen = `<div class="stage">
      <div class="stagelabel">🖼️ Imagen</div>
      ${kf ? `<img class="stagemedia" src="${fileUrl(kf.path)}?v=${kf.id}">` : '<span class="muted">sin imagen — pulsa "Generar imágenes" arriba</span>'}
      <div class="row">
        <input placeholder="Correcciones (ej: la camisa debe ser roja)" data-fb="${sc.id}">
        <button class="mini" data-regen="${sc.id}">🔄 Regenerar</button>
        <button class="mini" data-approve="${sc.id}">✅ Aprobar</button>
      </div>
    </div>`;

  const audio = `<div class="stage">
      <div class="stagelabel">🎙️ Audio</div>
      ${voice ? `<audio controls src="${fileUrl(voice.path)}?v=${voice.id}"></audio>` : '<span class="muted">sin voz — pulsa "Voz + música" arriba</span>'}
      <div class="row">
        <input placeholder="Ajuste de voz (ej: más lento y enfadado)" data-afb="${sc.id}">
        <button class="mini" data-reedit-voice="${sc.id}">🎙️ Reeditar voz</button>
      </div>
    </div>`;

  const video = `<div class="stage">
      <div class="stagelabel">🎬 Vídeo ${media && media.kind === 'preview' ? '<span class="ok-badge">🔊 con audio</span>' : ''}</div>
      ${media ? `<video class="stagemedia" controls preload="metadata" src="${fileUrl(media.path)}?v=${media.id}"></video>`
              : '<span class="muted">sin vídeo — pulsa "Animar aprobadas" arriba</span>'}
      <div class="row">
        <input placeholder="Mejora del vídeo (ej: más movimiento de cámara)" data-vfb="${sc.id}">
        <button class="mini" data-reedit-video="${sc.id}">🎬 Reeditar vídeo</button>
      </div>
    </div>`;

  return `<div class="scenehead"><strong>Escena ${sc.ord + 1}</strong>
      <span class="badge ${sc.approved ? 'ok' : ''}">${sc.approved ? '✅ aprobada' : 'pendiente'}</span></div>
    <div class="stages">${guion}${imagen}${IS_VIDEO ? audio + video : ''}</div>`;
}

function bindSceneCard(slot, sc) {
  const val = sel => (slot.querySelector(sel) || {}).value || '';
  slot.querySelectorAll('[data-save]').forEach(b => b.onclick = () => {
    const body = {};
    slot.querySelectorAll(`[data-sid="${b.dataset.save}"]`).forEach(e =>
      body[e.dataset.f] = e.dataset.f === 'duration_s' ? parseFloat(e.value) : e.value);
    api(`/api/scene/${b.dataset.save}/update`, body);
  });
  slot.querySelectorAll('[data-regen]').forEach(b => b.onclick = () =>
    api(`/api/scene/${b.dataset.regen}/regen`, {feedback: val(`[data-fb="${b.dataset.regen}"]`)}));
  slot.querySelectorAll('[data-approve]').forEach(b => b.onclick = () =>
    api(`/api/scene/${b.dataset.approve}/approve`));
  slot.querySelectorAll('[data-reedit-voice]').forEach(b => b.onclick = () =>
    api(`/api/scene/${b.dataset.reeditVoice}/reedit_voice`, {prompt: val(`[data-afb="${b.dataset.reeditVoice}"]`)}));
  slot.querySelectorAll('[data-reedit-video]').forEach(b => b.onclick = () => {
    if (confirm('Reeditar regenerará el clip con Veo (coste ~$0.15/seg del clip). ¿Continuar?'))
      api(`/api/scene/${b.dataset.reeditVideo}/reedit_video`, {prompt: val(`[data-vfb="${b.dataset.reeditVideo}"]`)});
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
