const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const state = {jobs: [], view: 'overview', filter: 'all', selected: null, previewUrl: null, loaded: false};
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const escape = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const parseDate = d => Date.parse(/^\d{4}-\d\d-\d\d \d\d:/.test(d) ? d.replace(' ', 'T') + 'Z' : d) || 0;
const jobTime = j => parseDate(j.created || j.created_at || '');
const REVIEW = ['AWAITING_SCRIPT', 'AWAITING_LOOK', 'AWAITING_DRAFT'];
const active = j => ['RUNNING', 'RENDERING', 'PENDING', 'QUEUED', ...REVIEW].includes(j.state);
const ready = j => j.state === 'READY_TO_PUBLISH';
const failed = j => ['FAILED', 'INTERRUPTED'].includes(j.state);
const labels = {AWAITING_SCRIPT: 'Review the script', AWAITING_LOOK: 'Review the look', AWAITING_DRAFT: 'Review the draft', RUNNING: 'In production', RENDERING: 'Rendering', PENDING: 'Queued', QUEUED: 'Queued', READY_TO_PUBLISH: 'Ready to watch', FAILED: 'Needs attention', INTERRUPTED: 'Interrupted', CANCELLED: 'Cancelled'};
const STEPS = [['beats', 'Story'], ['voice', 'Voice'], ['assets', 'Assets'], ['preview', 'Look'], ['draft', 'Draft'], ['sound mix', 'Sound'], ['final render', 'Export']];

/* ---------- Small UI helpers ---------- */
function notice(message, {reload = false} = {}) {
  const el = $('#notice'); el.textContent = message; el.hidden = !message;
  if (reload && message) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'notice-action'; button.textContent = 'Reload now';
    button.onclick = () => location.reload(); el.append(' ', button);
  }
}
function toast(message) {
  const el = $('#toast'); el.hidden = true; void el.offsetWidth; // restart the entrance animation
  el.textContent = message; el.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => el.hidden = true, 4200);
}
async function request(url, options = {}) {
  const response = await fetch(url, {...options, headers: {...(options.body ? {'Content-Type': 'application/json'} : {}), ...options.headers}});
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = Array.isArray(data.detail) ? data.detail.map(d => `${(d.loc || []).slice(1).join(' › ') || 'request'}: ${d.msg}`).join('; ') : data.detail;
    throw Object.assign(Error(typeof detail === 'string' && detail ? detail : `Request failed (${response.status})`), {status: response.status});
  }
  return response;
}
async function api(url, options) { return (await request(url, options)).json(); }

/* ---------- Theme ---------- */
function storedTheme() { try { return localStorage.getItem('studio-theme'); } catch { return null; } }
function applyTheme(theme) { document.documentElement.dataset.theme = theme; }
applyTheme(storedTheme() || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'));
$('#theme-toggle').addEventListener('click', () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  applyTheme(next); try { localStorage.setItem('studio-theme', next); } catch {}
});

/* ---------- Views with staggered entrance ---------- */
function animateIn(section) {
  if (reducedMotion) return;
  section.classList.remove('entering'); void section.offsetWidth; section.classList.add('entering');
  clearTimeout(section._t); section._t = setTimeout(() => section.classList.remove('entering'), 1100);
}
function view(name, {scroll = true} = {}) {
  state.view = name;
  $$('.view').forEach(el => { el.hidden = el.id !== name; if (!el.hidden) animateIn(el); });
  $$('nav [data-view]').forEach(el => el.classList.toggle('active', el.dataset.view === name));
  $('#crumb').textContent = {overview: 'Overview', create: 'Create a video', library: 'Video library', providers: 'Providers & settings'}[name];
  if (location.hash !== '#/' + name) history.replaceState(null, '', '#/' + name);
  notice(''); if (scroll) window.scrollTo({top: 0, behavior: reducedMotion ? 'auto' : 'smooth'});
  if (name === 'overview') renderProjects();
  if (name === 'create') readiness();
  if (name === 'providers') { if (!prefs.loaded) loadPreferences(false); renderStoryAIStatus(); }
}
$$('[data-view]').forEach(el => el.addEventListener('click', e => { e.preventDefault(); view(el.dataset.view); }));
$$('.stats .stat').forEach((el, i) => el.style.setProperty('--i', i));

/* ---------- Hero timecode (24 fps) ---------- */
(function timecode() {
  const el = $('#hero-timecode'); if (!el || reducedMotion) return;
  const start = performance.now(); const pad = n => String(n).padStart(2, '0');
  (function tick(now) {
    if (state.view === 'overview' && !document.hidden) {
      const frames = Math.floor((now - start) / (1000 / 24));
      const s = Math.floor(frames / 24);
      el.textContent = `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}:${pad(frames % 24)}`;
    }
    requestAnimationFrame(tick);
  })(start);
})();

/* ---------- Rolling counters (like the film engine's counters) ---------- */
function rollTo(el, value) {
  const from = Number(el.dataset.value || 0);
  el.dataset.value = value;
  if (from === value) { el.textContent = value; return; }
  if (reducedMotion) { el.textContent = value; return; }
  const t0 = performance.now(), dur = 900;
  (function frame(now) {
    const p = Math.min(1, (now - t0) / dur), eased = 1 - Math.pow(1 - p, 3);
    el.textContent = Math.round(from + (value - from) * eased);
    if (p < 1) requestAnimationFrame(frame);
    else { el.classList.remove('bump'); void el.offsetWidth; el.classList.add('bump'); }
  })(t0);
}

/* ---------- Templates & character count ---------- */
// Written in English; the planner tells the story in whichever Language is selected.
const templates = {
  story: 'On a rainy afternoon, Mira folds a paper boat for her little brother. When it floats away on the water, they clap with joy. Make a gentle cinematic animation of this story.',
  brand: 'A cinematic advert for the Fresh Tea brand: a tea garden, green leaves and a hot cup of tea. End on the line "Freshness in every sip".',
  explainer: 'Explain simply how a cup of tea is made from the tea leaf: picking the leaves, processing them, and brewing the tea.'
};
$$('[data-template]').forEach(el => el.addEventListener('click', () => {
  $('#story').value = templates[el.dataset.template]; count(); saveDraft(); view('create'); $('#story').focus();
}));
// The story being written survives a closed tab or a studio restart, until it is submitted.
const DRAFT = 'studio-draft';
function saveDraft() {
  try {
    const story = $('#story').value, notes = $('#changes').value;
    if (story || notes) localStorage.setItem(DRAFT, JSON.stringify({story, notes})); else localStorage.removeItem(DRAFT);
  } catch {}
}
function restoreDraft() {
  try {
    const draft = JSON.parse(localStorage.getItem(DRAFT) || '{}');
    if (!$('#story').value && draft.story) $('#story').value = draft.story;
    if (!$('#changes').value && draft.notes) $('#changes').value = draft.notes;
  } catch {}
  count();
}
$('#story').addEventListener('input', saveDraft); $('#changes').addEventListener('input', saveDraft);
function count() {
  const n = $('#story').value.length;
  $('#char-count').textContent = n.toLocaleString() + ' / 24,000';
  $('#char-count').classList.toggle('near', n > 21000);
}
$('#story').addEventListener('input', count);

/* ---------- Project cards ---------- */
// The CSP forbids inline style attributes, so per-item styles are applied through the CSSOM.
function applyStyles() {
  $$('[data-i]').forEach(el => el.style.setProperty('--i', el.dataset.i));
  $$('[data-w]').forEach(el => el.style.width = el.dataset.w + '%');
  $$('[data-delay]').forEach(el => el.style.animationDelay = el.dataset.delay + 'ms');
}
function progress(j) {
  const done = new Set(j.pipeline?.completed || []);
  return STEPS.filter(([k]) => done.has(k)).length / STEPS.length;
}
// "· हिन्दी · 30s": the language as people write it, then the length.
function details(j) {
  const language = String(j.language || '').split(' · ').pop().replace(/^.*\(([^)]*[^\x00-\x7f][^)]*)\)$/, '$1');   // "Bangla (বাংলা)" → বাংলা, "English (US)" stays
  return [language, j.duration ? j.duration + 's' : ''].filter(Boolean).map(t => ' · ' + escape(t)).join('');
}
function card(j, i) {
  const cls = ready(j) ? 'ready' : failed(j) ? 'failed' : REVIEW.includes(j.state) ? 'review' : active(j) ? 'active' : '';
  const title = j.title || j.run || `Untitled story · ${j.id.slice(0, 8)}`;
  const date = j.created || j.created_at;
  const thumb = j.local && j.thumb ? `<img loading="lazy" alt="" src="/local/jobs/${encodeURIComponent(j.id)}/artifact?file=${encodeURIComponent(j.thumb)}">` : '';
  const icon = ready(j) ? '▶' : active(j) ? '◷' : failed(j) ? '!' : '✦';
  const pct = j.local && j.pipeline && !ready(j) ? progress(j) : null;
  const stage = j.local && j.state === 'RUNNING' && j.stage ? j.stage : null;
  return `<button class="project-card" data-i="${i}" data-job="${escape(j.key)}">
    <div class="project-art p${i % 4}${thumb ? ' has-thumb' : ''}">${thumb}<span class="shade"></span>
      <span class="art-mode">${j.local ? 'LOCAL CINEMATIC' : j.demo ? 'DEMO PREVIEW' : 'CONNECTED PROVIDERS'}</span>
      <span class="play${active(j) && !REVIEW.includes(j.state) ? ' spin' : ''}">${icon}</span>
      <span class="art-state">${escape(stage || (j.local ? 'STORY IN MOTION' : 'VERTICAL FILM'))}</span></div>
    <div class="project-info"><h3>${escape(title)}</h3>
      <div><span>${date ? escape(new Date(parseDate(date)).toLocaleDateString('en-GB', {month: 'short', day: 'numeric'})) : 'Saved project'}${details(j)}</span>
      <span class="badge ${cls}">${escape(labels[j.state] || j.state)}</span></div>
      ${pct !== null ? `<div class="progress${j.state === 'RUNNING' ? ' live' : ''}"><i data-w="${Math.max(6, pct * 100)}"></i></div>` : ''}
    </div></button>`;
}
function renderProjects() {
  const jobs = state.jobs;
  rollTo($('#total-count'), jobs.length); rollTo($('#active-count'), jobs.filter(active).length);
  rollTo($('#ready-count'), jobs.filter(ready).length); rollTo($('#failed-count'), jobs.filter(failed).length);
  $('#recent-count').textContent = jobs.length;
  const empty = '<div class="empty"><span>✦</span><h3>Your next great story belongs here.</h3><p>Create your first video and watch your collection grow.</p><button class="primary" data-go="create">＋ Create a video</button></div>';
  $('#recent-projects').innerHTML = jobs.slice(0, 3).map(card).join('') || (state.loaded ? empty : $('#recent-projects').innerHTML);
  const term = $('#search').value.toLowerCase();
  const filtered = jobs.filter(j => (state.filter === 'all' || (state.filter === 'ready' ? ready(j) : state.filter === 'active' ? active(j) : failed(j)))
    && `${j.title || ''} ${j.id} ${j.run || ''} ${j.language || ''}`.toLowerCase().includes(term));
  $('#all-projects').innerHTML = filtered.map(card).join('') || '<div class="empty"><span>▦</span><h3>No projects here yet.</h3><p>Try a different filter or start a new story.</p></div>';
  applyStyles();
  $$('.project-card').forEach(el => el.addEventListener('click', () => openProject(state.jobs.find(j => j.key === el.dataset.job))));
  $$('[data-go]').forEach(el => el.addEventListener('click', () => view(el.dataset.go)));
}
// Avoid re-rendering cards (and replaying their entrance) when nothing visible changed.
const signature = jobs => JSON.stringify(jobs.map(j => [j.key, j.state, j.stage, j.thumb, j.title, j.language, (j.pipeline?.completed || []).length]));

async function refresh() {
  const button = $('#refresh'); button.classList.add('spinning');
  try {
    const results = await Promise.allSettled([api('/local/jobs'), api('/api/jobs')]);
    const jobs = [];
    if (results[0].status === 'fulfilled') jobs.push(...results[0].value.map(j => ({...j, local: true, key: 'local:' + j.id})));
    if (results[1].status === 'fulfilled') jobs.push(...results[1].value.map(j => ({...j, local: false, key: 'api:' + j.id})));
    const sorted = jobs.sort((a, b) => jobTime(b) - jobTime(a));
    const changed = !state.loaded || signature(sorted) !== signature(state.jobs);
    state.jobs = sorted; state.loaded = true;
    const connected = results.every(r => r.status === 'fulfilled');
    // The studio makes a new page session each time it starts, so an old tab gets 401 until it reloads.
    const expired = results.some(r => r.status === 'rejected' && r.reason?.status === 401 && /dashboard first/i.test(r.reason.message));
    if (expired && !state.expired) notice('The studio was restarted, so this page lost its connection.', {reload: true});
    else if (!expired && state.expired) notice('');
    state.expired = expired;
    $('#connection').classList.toggle('off', !connected);
    $('#connection').innerHTML = '<i></i>' + (expired ? 'Reload the page' : connected ? 'Studio connected' : results[0].status === 'fulfilled' ? 'Local studio · API offline' : 'Studio offline');
    if (changed) renderProjects();
    if (state.selected) {
      const updated = jobs.find(j => j.key === state.selected.key);
      if (updated) {
        const stateChanged = state.selected.state !== updated.state, stageChanged = state.selected.stage !== updated.stage;
        state.selected = updated;
        if (stateChanged) { await openProject(updated); return; }
        if ((updated.error || '') !== $('#job-state').dataset.error) showState(updated);   // redraw only on change, so open details stay open
        if (updated.local && active(updated)) {
          loadLog(updated);
          if (stageChanged) await cinematicReview(updated);
          if (updated.stage && updated.state === 'RUNNING') $('#stage-description').textContent = 'Current stage: ' + updated.stage + ' …';
        }
      }
    }
  } finally { setTimeout(() => button.classList.remove('spinning'), 400); }
}
$('#refresh').addEventListener('click', () => refresh().catch(e => notice(e.message)));
$('#search').addEventListener('input', renderProjects);
function setFilter(name) {
  state.filter = name; $$('[data-filter]').forEach(b => b.classList.toggle('active', b.dataset.filter === name)); renderProjects();
}
$$('[data-filter]').forEach(el => el.addEventListener('click', () => setFilter(el.dataset.filter)));
// The overview counters open the library already filtered to what they count.
$$('[data-go-filter]').forEach(el => el.addEventListener('click', () => { $('#search').value = ''; view('library'); setFilter(el.dataset.goFilter); }));

/* ---------- Create form ---------- */
function mode() { return new FormData($('#create-form')).get('mode'); }
// Label each story AI with its model and grey out the ones without a key in .env.
async function loadStoryAIs() {
  let list;
  try { list = await api('/api/story-ais'); } catch { return; }   // API offline: keep the plain list
  const select = $('#story-ai'), cost = {lowest: 'lowest cost', low: 'low cost', higher: 'higher cost'};
  for (const ai of list) {
    const option = select.querySelector(`option[value="${ai.id}"]`); if (!option) continue;
    option.textContent = `${ai.label} · ${ai.model} · ${cost[ai.cost] || ai.cost}` + (ai.connected ? '' : ' (not connected)');
    option.disabled = !ai.connected;
  }
  const names = list.filter(ai => ai.connected).map(ai => ai.label);
  select.querySelector('option[value="auto"]').textContent = names.length ? `Auto · cheapest of ${names.join(', ')}` : 'Auto · no story AI connected yet';
  try { const saved = localStorage.getItem('story-ai'); const o = saved && select.querySelector(`option[value="${saved}"]`); if (o && !o.disabled) select.value = saved; } catch {}
}
$('#story-ai').addEventListener('change', e => { try { localStorage.setItem('story-ai', e.target.value); } catch {} });

// What the chosen workflow still needs, checked against the connections list before anything is queued.
async function readiness() {
  const box = $('#readiness'), m = mode();
  if (m === 'demo') { box.hidden = true; return; }
  const data = connections.loaded ? connections : await loadConnections().catch(() => null);
  if (!data) { box.hidden = true; return; }   // API offline: the submit itself will explain
  if (mode() !== m) return;                    // the workflow changed while checking; that call redraws
  const on = id => data.services.some(s => s.id === id && s.connected);
  const missing = [];
  if (m === 'local' && !on('codex')) missing.push('Local cinematic films need the <b>Codex app</b> to write the script. Install it from the Microsoft Store and sign in with your ChatGPT account.');
  if (m === 'provider') {
    if (!['gemini', 'openai', 'claude'].some(on)) missing.push('Connect a <b>story AI</b> (Gemini is the cheapest) to write the scenes.');
    if (!['muse', 'runway'].some(on)) missing.push('Connect a <b>video service</b> (Muse Video or Runway) to generate the clips.');
  }
  box.className = 'readiness ' + (missing.length ? 'warn' : 'ok'); box.hidden = false;
  box.innerHTML = missing.length
    ? `<div><strong>Before you create</strong><ul>${missing.map(t => `<li>${t}</li>`).join('')}</ul></div>
       <div class="readiness-actions"><button type="button" class="secondary small" data-recheck>Check again</button>${m === 'provider' ? '<button type="button" class="primary small" data-view-go="providers">Connect accounts →</button>' : ''}</div>`
    : `<div><strong>✓ Ready</strong> ${m === 'local' ? 'Codex writes the script; voice, render and sound run free on this PC.' : 'A story AI and a video service are connected.'}</div>`;
  box.querySelector('[data-recheck]')?.addEventListener('click', async () => { connections.loaded = false; await readiness(); toast('Checked again.'); });
  box.querySelector('[data-view-go]')?.addEventListener('click', () => view('providers'));
}

function changeMode() {
  readiness();
  const local = mode() === 'local';
  $$('.local-field').forEach(el => el.hidden = !local);
  $$('.api-field').forEach(el => el.hidden = local);
  $('#output-summary').textContent = local ? 'Cinematic animation + MP4' : mode() === 'demo' ? 'Sample preview + MP4' : 'Generated media + MP4';
  $('#mode-note').textContent = local ? 'Internet required. Your prompt goes to Codex and narration text to the speech service. Nothing is published automatically.'
    : mode() === 'demo' ? 'A pipeline test with colored scenes and captions. No generated footage or voice. No API keys required.'
    : 'Uses your configured API services. Generation may spend provider credits. Review your video before publishing.';
}
$$('[name="mode"]').forEach(el => el.addEventListener('change', changeMode));

// Show what a render will spend before it is queued. Muse bills per second of source video
// (src/main.py prints the same figure); upscaling to the export size happens locally for free.
function costEstimate() {
  const form = $('#create-form').elements, m = mode();
  let text = 'Codex planning only · voice, render and sound are free';
  if (m === 'demo') text = 'Free';
  else if (m === 'provider') {
    const seconds = Number(form.namedItem('scene_count').value) * Number(form.namedItem('seconds_per_scene').value);
    const rate = form.namedItem('resolution').value === '1080p' ? 75 : 40;
    text = `About ${(seconds * rate).toLocaleString()} Muse credits for ${seconds}s` + (rate === 75 ? ' (720p source: ' + (seconds * 40).toLocaleString() + ')' : '');
  }
  $('#cost-estimate').textContent = text;
}
['scene_count', 'seconds_per_scene', 'resolution'].forEach(n => $('#create-form').elements.namedItem(n).addEventListener('input', costEstimate));
$$('[name="mode"]').forEach(el => el.addEventListener('change', costEstimate));
const PORTRAIT = {'640x360': '360x640', '1280x720': '720x1280', '1920x1080': '1080x1920', '2560x1440': '1440x2560', '3840x2160': '2160x3840'};

$('#create-form').addEventListener('submit', async event => {
  event.preventDefault(); notice('');
  const form = new FormData(event.currentTarget); const button = $('#submit-video'); button.disabled = true;
  try {
    let result;
    if (form.get('mode') === 'local') {
      if (form.has('music') && !form.has('audio')) throw Error('The background score needs narration. Turn on “Voice & audio” or untick the score.');
      if (!form.has('audio')) toast('Voice disabled for this request.');
      const portrait = form.get('aspect') === '9:16';
      const prompt = `${form.get('story')}\nDirector notes: ${form.get('final_changes')}\nLanguage: ${form.get('language')}. Visual style: ${form.get('style')}. Duration: ${form.get('duration')} seconds. Aspect ratio: ${form.get('aspect')}. Draft size: ${form.get('local_size')}. Voice: ${form.has('audio') ? 'enabled' : 'disabled; do not synthesize voice; make genuine scene timings for a silent film'}. Burn captions: ${form.has('burn_captions')}. ${portrait ? 'Use a portrait render size (360x640 or 720x1280), matching requested quality.' : ''} Even with captions disabled, save the final video as out/final-bangla.mp4. Keep all output in the assigned project folder.`;
      result = await api('/local/jobs', {method: 'POST', body: JSON.stringify({prompt, options: {
        look: form.get('look'), caption_style: form.get('caption_style'), voice: form.get('voice'), voice_source: form.get('voice_source'),
        music: form.has('music') ? 'audio/music.mp3' : null, review: form.has('review'), sfx: form.has('sfx'), archive: form.has('archive'),
        maps: form.has('maps'), audio: form.has('audio'), captions: form.has('burn_captions'), duration: Number(form.get('duration')),
        language: form.get('language'), size: portrait ? PORTRAIT[form.get('local_size')] : form.get('local_size')}})});
    } else {
      if (form.get('mode') === 'provider' && !confirm('This render uses connected providers and may spend credits. Queue this video?')) return;
      const brief = {story: form.get('story'), final_changes: form.get('final_changes'), language: form.get('language'), style: form.get('style'),
        scene_count: Number(form.get('scene_count')), seconds_per_scene: Number(form.get('seconds_per_scene')), resolution: form.get('resolution'),
        export_resolution: form.get('export_resolution'), audio: form.has('audio'), burn_captions: form.has('burn_captions'),
        made_for_kids: form.has('made_for_kids'), synthetic_disclosure: form.has('synthetic_disclosure'), story_ai: form.get('story_ai')};
      result = await api('/api/jobs', {method: 'POST', body: JSON.stringify({brief, demo: form.get('mode') === 'demo'})});
    }
    $('#story').value = ''; $('#changes').value = ''; saveDraft(); count();   // the project keeps its own copy of the story
    await refresh(); view('library'); toast('Your story is in production.');
    const j = state.jobs.find(j => j.id === result.id); if (j) openProject(j);
  } catch (e) { notice(e.message); window.scrollTo({top: 0, behavior: 'smooth'}); }
  finally { button.disabled = false; }
});
$('#create-form').addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !$('#submit-video').disabled) { e.preventDefault(); $('#create-form').requestSubmit(); }
});
/* ---------- Languages: one list (web/languages.json) drives language and voice ---------- */
const languages = {list: [], byCode: {}};
const languageLabel = l => l.native === l.name ? l.name : `${l.name} · ${l.native}`;   // what the planner reads
function fillVoices(code, keep) {
  const lang = languages.byCode[code]; if (!lang) return;
  const select = $('#voice');
  select.innerHTML = lang.voices.map(([id, name, g]) => `<option value="${escape(id)}">${escape(name)} · ${g === 'F' ? 'female' : 'male'}</option>`).join('');
  if (keep && lang.voices.some(([id]) => id === keep)) select.value = keep;
}
async function loadLanguages() {
  try { languages.list = await (await fetch('/languages.json')).json(); } catch { return; }   // keep the built-in two
  languages.byCode = Object.fromEntries(languages.list.map(l => [l.code, l]));
  const select = $('#language');
  select.innerHTML = languages.list.map(l => `<option value="${escape(languageLabel(l))}" data-code="${l.code}">${escape(l.native === l.name ? l.name : l.native + ' · ' + l.name)}</option>`).join('');
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('studio-language') || '{}'); } catch {}
  const code = languages.byCode[saved.code] ? saved.code : 'bn-BD';
  select.value = languageLabel(languages.byCode[code]);
  fillVoices(code, saved.voice);
}
function rememberLanguage() {
  const code = $('#language').selectedOptions[0]?.dataset.code;
  try { localStorage.setItem('studio-language', JSON.stringify({code, voice: $('#voice').value})); } catch {}
}
$('#language').addEventListener('change', () => { fillVoices($('#language').selectedOptions[0].dataset.code); rememberLanguage(); });
$('#voice').addEventListener('change', rememberLanguage);

/* ---------- Project dialog ---------- */
// Errors from production tools are written for developers; lead with what happened and what to do.
function plainError(error) {
  const text = String(error || '');
  if (/codex\.exe|codex.*returned non-zero/i.test(text)) return 'Codex could not write the script. Check that the Codex app is open and signed in, then press Retry.';
  if (/NoAudioReceived|Edge voice gave no audio/i.test(text)) return 'The free voice service did not answer. Press Retry in a minute.';
  if (/ffmpeg|ffprobe/i.test(text) && /not found|missing|No such file/i.test(text)) return 'FFmpeg is missing. Run INSTALL-LOCAL.cmd once, then press Retry.';
  if (/failed \(exit \d+\)|returned non-zero|Traceback|[A-Z]:\\/.test(text)) return 'A production step stopped. Press Retry; if it happens again, open the Production log below.';
  return text;
}
function showState(job) {
  const el = $('#job-state'); el.className = failed(job) ? 'job-state bad' : 'job-state'; el.dataset.error = job.error || '';
  el.textContent = labels[job.state] || job.state;
  if (!job.error) return;
  const reason = plainError(job.error);
  el.append(document.createElement('br'), reason);
  if (reason !== job.error) {
    const more = document.createElement('details'); more.className = 'tech';
    more.innerHTML = '<summary>Technical details</summary><pre></pre>'; more.querySelector('pre').textContent = job.error;
    el.append(more);
  }
}
async function loadLog(job) {
  try { const pre = $('#job-log'); const atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
    pre.textContent = (await api(`/local/jobs/${job.id}/log`)).log; if (atEnd) pre.scrollTop = pre.scrollHeight;
  } catch (e) { $('#job-log').textContent = e.message; }
}
async function openProject(job) {
  if (!job) return;
  state.selected = job;
  $('#preview-title').textContent = job.title || job.run || 'Your story';
  showState(job);
  const video = $('#video-preview'); video.pause(); video.removeAttribute('src'); video.hidden = true;
  // Show a real frame of the film instead of a black box before playback.
  if (job.local && job.thumb) video.poster = `/local/jobs/${encodeURIComponent(job.id)}/artifact?file=${encodeURIComponent(job.thumb)}`;
  else video.removeAttribute('poster');
  video.load();
  $('#download-video').hidden = true; $('#download-srt').hidden = true; $('#publish-section').hidden = true; $('#job-action').hidden = true;
  $('#job-log').textContent = ''; $('#cinematic-review').hidden = true; $('#logs-block').hidden = !job.local;
  deleteButton(job);
  if (!$('#preview-dialog').open) $('#preview-dialog').showModal();
  try {
    if (ready(job)) {
      const url = job.local ? `/local/jobs/${job.id}/video` : `/api/jobs/${job.id}/preview`;
      if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
      let src = url;
      if (!job.local) { state.previewUrl = URL.createObjectURL(await (await request(url)).blob()); src = state.previewUrl; }
      video.src = src; video.hidden = false; $('#download-video').href = src; $('#download-video').hidden = false;
      if (job.local) { $('#download-srt').href = `/local/jobs/${job.id}/subtitles`; $('#download-srt').hidden = false; }
      else if (!job.demo) { $('#publish-section').hidden = false; await deliveries(job); }
    }
    if (job.local) { await loadLog(job); await cinematicReview(job); }
    else if (['PENDING', 'FAILED'].includes(job.state)) {
      const button = $('#job-action'); button.hidden = false;
      button.textContent = job.state === 'PENDING' ? 'Cancel queued job' : 'Recover job';
      button.onclick = async () => {
        try { await api(`/api/jobs/${job.id}/${job.state === 'PENDING' ? 'cancel' : 'recover'}`, {method: 'POST'}); $('#preview-dialog').close(); await refresh(); toast('Job updated.'); }
        catch (e) { toast(e.message); }
      };
    }
  } catch (e) { $('#job-state').textContent = e.message; }
}
// Two presses, so a stray click never removes a film: the first arms the button for a few seconds.
function deleteButton(job) {
  const button = $('#delete-project'); clearTimeout(button._t);
  button.hidden = !job.local || job.state === 'RUNNING'; button.textContent = 'Delete project'; button.classList.remove('armed'); button.disabled = false;
  button.onclick = async () => {
    if (!button.classList.contains('armed')) {
      button.classList.add('armed'); button.textContent = 'Press again to delete its folder for good';
      button._t = setTimeout(() => { button.classList.remove('armed'); button.textContent = 'Delete project'; }, 5000); return;
    }
    button.disabled = true;
    const video = $('#video-preview'); video.pause(); video.removeAttribute('src'); video.load();   // Windows keeps a playing file locked
    try { await api(`/local/jobs/${encodeURIComponent(job.id)}`, {method: 'DELETE'}); $('#preview-dialog').close(); await refresh(); toast('Project deleted.'); }
    catch (e) { toast(e.message); button.disabled = false; }
  };
}
$('#close-dialog').onclick =() => { $('#video-preview').pause(); $('#preview-dialog').close(); state.selected = null; };
$('#preview-dialog').addEventListener('close', () => { $('#video-preview').pause(); state.selected = null; });

async function cinematicReview(job) {
  const manifest = await api(`/local/jobs/${job.id}/manifest`); const pipeline = manifest.pipeline || {};
  if (!pipeline.status) return;
  const effectiveStatus = job.state === 'RUNNING' ? 'RUNNING' : pipeline.status;
  $('#cinematic-review').hidden = false;
  const done = new Set(pipeline.completed || []);
  $('#workflow-stages').innerHTML = STEPS.map(([key, label]) => `<li class="${done.has(key) ? 'done' : pipeline.stage === key ? 'current' : ''}">${label}</li>`).join('');
  const descriptions = {
    AWAITING_SCRIPT: 'Review the narration, visual heroes and estimated beat table. Approval starts voice, assets and preview rendering.',
    AWAITING_LOOK: 'Check the preview frames and contact sheet. Approval renders a draft of up to 30 seconds.',
    AWAITING_DRAFT: 'Watch the draft above. Approval builds the sound effects and mix, then renders the full film with captions.',
    READY_TO_PUBLISH: 'The final video passed media validation. Download the MP4, subtitle file and credits.',
    FAILED: 'This stage stopped (the reason is above). Everything finished so far is saved: press Retry to continue from here.'};
  $('#stage-description').textContent = (descriptions[effectiveStatus] || 'Current stage: ' + (pipeline.stage || 'starting') + ' …')
    + (pipeline.actual_duration ? ' Narration timeline: ' + Number(pipeline.actual_duration).toFixed(1) + ' seconds.' : '');
  $('#beat-table').textContent = manifest.files['beats.md'] || manifest.files['script.json'] || 'Preparing the script…';
  $('#asset-credits').textContent = manifest.files['credits.md'] || 'Credits will be generated during asset preparation.';
  $('#open-project-folder').onclick = async () => { try { await api(`/local/jobs/${job.id}/folder`, {method: 'POST'}); } catch (e) { toast(e.message); } };
  $('#download-credits').hidden = !manifest.files['credits.md'];
  $('#download-credits').href = `/local/jobs/${job.id}/artifact?file=credits.md`;
  $('#download-beats').href = `/local/jobs/${job.id}/artifact?file=beats.md`;
  $('#preview-frames').innerHTML = manifest.previews.map((file, i) =>
    `<img loading="lazy" data-delay="${i * 70}" class="${file.includes('/strip_') ? 'strip' : ''}" alt="Cinematic preview frame" src="/local/jobs/${job.id}/artifact?file=${encodeURIComponent(file)}">`).join('');
  applyStyles();
  renderChecks(job, pipeline, effectiveStatus);
  if (pipeline.status === 'AWAITING_SCRIPT') $('#beat-review').open = true;
  if (pipeline.status === 'AWAITING_DRAFT') { $('#video-preview').src = `/local/jobs/${job.id}/artifact?file=out/draft.mp4`; $('#video-preview').hidden = false; }
  const actions = {AWAITING_SCRIPT: ['preview', 'Approve script → Build look preview'], AWAITING_LOOK: ['draft', 'Approve look → Render draft'],
    AWAITING_DRAFT: ['finish', 'Approve draft → Final export'], FAILED: ['retry', 'Retry failed stage']};
  $('#revision-panel').hidden = ![...REVIEW, 'FAILED'].includes(effectiveStatus);
  $('#recheck-plan').hidden = !['AWAITING_SCRIPT', 'FAILED'].includes(effectiveStatus);
  $('#recheck-plan').onclick = async () => { try { await api(`/local/jobs/${job.id}/action`, {method: 'POST', body: JSON.stringify({action: 'prepare'})}); await refresh(); } catch (e) { toast(e.message); } };
  $('#revise-plan').onclick = async () => {
    const notes = $('#revision-notes').value.trim(); if (!notes) { toast('Describe the changes first.'); return; }
    try { await api(`/local/jobs/${job.id}/action`, {method: 'POST', body: JSON.stringify({action: 'revise', notes})}); $('#revision-notes').value = ''; await refresh(); }
    catch (e) { toast(e.message); }
  };
  const button = $('#continue-stage'); button.hidden = !actions[effectiveStatus];
  if (actions[effectiveStatus]) {
    const [action, label] = actions[effectiveStatus]; button.textContent = label; button.disabled = false;
    button.onclick = async () => {
      button.disabled = true;
      try { await api(`/local/jobs/${job.id}/action`, {method: 'POST', body: JSON.stringify({action})}); await refresh(); toast('Production stage started.'); }
      catch (e) { toast(e.message); button.disabled = false; }
    };
  }
}

// Automatic checks the cinematic-film skill asks for: beat-table lint, look review, suspect voice cuts.
function renderChecks(job, pipeline, status) {
  const groups = [
    ['Script checks', 'Beat-table lint: fix these before approving the script.', pipeline.lint || []],
    ['Look checks', 'Found automatically in the preview stills and camera moves.', (pipeline.look_review || []).filter(w => w.kind !== 'info').map(w => w.message)],
    ['Voice checks', 'Listen to these lines before approving.', pipeline.voice_flags || []]];
  const box = $('#review-checks'); const shown = groups.filter(([, , items]) => items.length);
  box.hidden = !shown.length;
  if (!shown.length) { box.innerHTML = ''; return; }
  box.innerHTML = shown.map(([title, hint, items]) => `<div class="check-group"><h4><span class="check-count">${items.length}</span>${escape(title)}</h4>
    <p class="muted">${escape(hint)}</p><ul>${items.map(i => `<li>${escape(i)}</li>`).join('')}</ul></div>`).join('')
    + ((pipeline.lint || []).length && ['AWAITING_SCRIPT', 'FAILED'].includes(status) ? '<button id="fix-lint" class="secondary" type="button">✦ Fix these with Codex</button>' : '');
  const fix = $('#fix-lint');
  if (fix) fix.onclick = async () => {
    fix.disabled = true;
    try { await api(`/local/jobs/${job.id}/action`, {method: 'POST', body: JSON.stringify({action: 'revise', notes: 'Fix every warning in the beat-table Lint section.'})}); await refresh(); toast('Codex is fixing the script.'); }
    catch (e) { toast(e.message); fix.disabled = false; }
  };
}

/* ---------- Publishing (provider mode) ---------- */
async function deliveries(job) {
  const rows = await api(`/api/jobs/${job.id}/deliveries`);
  $('#deliveries').innerHTML = rows.map(r => `<p class="muted">${escape(r.platform)} · ${escape(r.state)} ${r.publish_at ? '· ' + escape(new Date(r.publish_at).toLocaleString()) : ''}${r.state === 'SUBMITTED' ? ` <button class="text-button" data-metrics="${escape(r.platform)}">View metrics →</button>` : ''}</p>`).join('');
  $$('[data-metrics]').forEach(el => el.onclick = async () => { try { toast(JSON.stringify(await api(`/api/jobs/${job.id}/analytics/${el.dataset.metrics}`))); } catch (e) { toast(e.message); } });
}
$('#publish-form').onsubmit = async e => {
  e.preventDefault(); const form = new FormData(e.currentTarget);
  if (!confirm(form.has('public') ? 'Publish this video publicly?' : 'Submit a private YouTube video or Facebook draft?')) return;
  try {
    const when = form.get('schedule');
    await api(`/api/jobs/${state.selected.id}/deliveries`, {method: 'POST', body: JSON.stringify({platform: form.get('platform'), public: form.has('public'), ...(when ? {publish_at: new Date(when).toISOString()} : {})})});
    await deliveries(state.selected); toast('Upload scheduled.');
  } catch (e) { toast(e.message); }
};

/* ---------- Providers ---------- */
// Saved settings load before Save is enabled: saving a blank form would erase every saved choice.
const prefs = {loaded: false};
const prefForm = () => $('#provider-form');
function prefStatus(text) { $('#prefs-status').textContent = text; }
async function loadPreferences(showToast) {
  prefStatus('Loading your saved settings…'); $('#save-prefs').disabled = true;
  try {
    const data = await api('/api/providers');
    for (const [key, value] of Object.entries(data)) {
      const input = prefForm().elements.namedItem(key);
      if (input) input.value = value == null ? '' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
    }
    prefForm().querySelector('details.advanced').open = Boolean(data.story_routing);
    prefs.loaded = true; $('#save-prefs').disabled = false;
    const count = Object.values(data).filter(v => v !== null && v !== '').length;
    prefStatus(count ? `${count} saved setting${count === 1 ? '' : 's'}. Blank fields stay on Automatic.`
                     : 'Everything is on Automatic. Change only what you need.');
    if (showToast) toast('Unsaved changes undone.');
  } catch (e) {
    prefs.loaded = false;
    prefStatus(`Could not load your saved settings (${e.message}). Saving is off so nothing is overwritten.`);
  }
}
$('#load-defaults').onclick = () => loadPreferences(true);
prefForm().onsubmit = async e => {
  e.preventDefault(); notice('');
  if (!prefs.loaded) { notice('Your saved settings have not loaded, so saving is off to avoid overwriting them. Press Reload saved settings.'); return; }
  const payload = {};
  for (const [key, raw] of new FormData(e.currentTarget)) {
    const value = raw.trim();
    if (!value) { payload[key] = null; continue; }
    if (key === 'story_routing') {
      try { payload[key] = JSON.parse(value); }
      catch (err) { prefForm().querySelector('details.advanced').open = true; notice(`Story routing JSON has a typo (${err.message}). Fix it or clear the box.`); return; }
    } else if (key === 'story_budget_usd') {
      const dollars = Number(value);
      if (!Number.isFinite(dollars) || dollars < 0) { notice('Story budget must be an amount in dollars, 0 or more.'); return; }
      payload[key] = dollars;
    } else payload[key] = value;
  }
  if (payload.video_provider && payload.video_provider === payload.video_fallback) { notice('Pick a different backup video provider, or No backup.'); return; }
  const button = $('#save-prefs'); button.disabled = true;
  try { await api('/api/providers', {method: 'PUT', body: JSON.stringify(payload)}); await loadPreferences(false); toast('Provider preferences saved.'); }
  catch (err) { notice('Not saved: ' + err.message); }
  finally { button.disabled = !prefs.loaded; }
};

/* ---------- AI account connections ---------- */
const connections = {services: [], google: {}, current: null, loaded: false};
async function loadConnections() {
  const data = await api('/api/connections');
  Object.assign(connections, {services: data.services, google: data.google, loaded: true});
  return connections;
}
const GOOGLE_G = '<svg viewBox="0 0 18 18" aria-hidden="true"><path fill="#4285F4" d="M17.6 9.2c0-.6-.1-1.2-.2-1.7H9v3.3h4.8a4.1 4.1 0 0 1-1.8 2.7v2.2h2.9c1.7-1.6 2.7-3.9 2.7-6.5z"/><path fill="#34A853" d="M9 18c2.4 0 4.5-.8 6-2.2l-2.9-2.2c-.8.5-1.8.9-3.1.9-2.4 0-4.4-1.6-5.1-3.7H.9v2.3A9 9 0 0 0 9 18z"/><path fill="#FBBC05" d="M3.9 10.8a5.4 5.4 0 0 1 0-3.5V5H.9a9 9 0 0 0 0 8.1l3-2.3z"/><path fill="#EA4335" d="M9 3.6c1.3 0 2.5.5 3.5 1.4l2.6-2.6A9 9 0 0 0 .9 5l3 2.3C4.6 5.2 6.6 3.6 9 3.6z"/></svg>';
async function renderStoryAIStatus() {
  const box = $('#connection-groups');
  try {
    const data = await loadConnections();
    if (state.view === 'create') readiness();
    const ready = data.services.filter(r => r.connected).length;
    $('#connections-summary').textContent = `${ready} of ${data.services.length} connected. Press Connect on a service and follow the steps. Keys are tested first and stay on this PC.`;
    const g = $('#google-state'); g.hidden = false;
    g.className = 'google-state ' + (data.google.signed_in ? 'on' : '');
    g.innerHTML = GOOGLE_G + (data.google.signed_in ? 'Signed in with Google' : data.google.cli ? 'Google: not signed in' : 'Google sign-in: Cloud CLI not installed');
    const groups = ['Story', 'Video', 'Images', 'Voice'].filter(g => data.services.some(r => r.group === g));
    box.innerHTML = groups.map(group => `<div class="connection-group"><h4>${escape(group)}</h4><div class="connection-cards">` +
      data.services.filter(r => r.group === group).map(r => `
        <article class="connection-card ${r.connected ? 'on' : ''}" data-service="${escape(r.id)}">
          <span class="service-mark" aria-hidden="true">${escape(r.label.slice(0, 1))}</span>
          <div class="service-text"><b>${escape(r.label)}</b><small>${escape(r.use)}</small>
            ${r.fields ? r.fields.filter(f => f.saved).map(f => `<small class="saved-key">${escape(f.saved)}</small>`).join('') : `<small>${escape(r.fixed)}</small>`}</div>
          <span class="service-state">${r.connected ? 'Connected' : 'Not connected'}</span>
          ${r.fields ? `<button type="button" class="${r.connected ? 'secondary' : 'primary'} small" data-connect="${escape(r.id)}">${r.connected ? 'Manage' : r.google ? GOOGLE_G + 'Connect' : 'Connect'}</button>` : ''}
        </article>`).join('') + '</div></div>').join('');
    $$('[data-connect]').forEach(b => b.onclick = () => openConnect(b.dataset.connect));
  } catch (e) { box.innerHTML = `<p class="muted">${escape(e.message)}</p>`; }
}

function connectResult(text, ok) {
  const el = $('#connect-result'); el.hidden = !text; el.textContent = text; el.className = 'connect-result ' + (ok ? 'ok' : 'bad');
}
function openConnect(id) {
  const r = connections.services.find(s => s.id === id); connections.current = r;
  $('#connect-group').textContent = r.group + ' · ' + r.use;
  $('#connect-title').textContent = (r.connected ? 'Manage ' : 'Connect ') + r.label;
  $('#connect-steps').innerHTML = r.steps.map(step => `<li>${escape(step)}</li>`).join('');
  const signin = r.google === 'signin'
    ? `<button type="button" class="google-button" id="google-sign-in">${GOOGLE_G}Sign in with Google</button>`
    : `<a class="${r.google ? 'google-button' : 'secondary'}" href="${escape(r.get_key)}" target="_blank" rel="noopener noreferrer">${r.google ? GOOGLE_G + 'Sign in with Google to get a key' : 'Open ' + escape(r.label) + ' to get a key ↗'}</a>`;
  $('#connect-signin').innerHTML = signin + (r.google === 'signin' && connections.google.signed_in ? '<span class="signed">✓ Signed in</span>' : '');
  $('#connect-note').hidden = !r.note; $('#connect-note').textContent = r.note;
  $('#connect-fields').innerHTML = r.fields.map(f => `<label>${escape(f.label)}
      <input name="${escape(f.env)}" ${f.secret ? 'type="password" autocomplete="off"' : 'type="text"'} spellcheck="false"
        value="${escape(f.value || '')}" placeholder="${escape(f.saved ? 'Saved ' + f.saved + ' · leave blank to keep it' : f.default || (f.optional ? 'Optional' : 'Paste here'))}"></label>`).join('');
  $('#connect-save-untested').hidden = !r.testable;
  $('#connect-remove').hidden = !r.connected;
  connectResult('');
  const button = $('#google-sign-in');
  if (button) button.onclick = async () => {
    try { const reply = await api('/api/connections/google/sign-in', {method: 'POST'}); connectResult(reply.message, true); waitForGoogle(); }
    catch (e) { connectResult(e.message, false); }
  };
  $('#connect-dialog').showModal();
  ($('#connect-fields input:not([value])') || $('#connect-fields input'))?.focus();
}
async function waitForGoogle() {
  for (let i = 0; i < 40 && $('#connect-dialog').open; i++) {
    await new Promise(r => setTimeout(r, 3000));
    const data = await api('/api/connections').catch(() => null);
    if (data?.google.signed_in) { connections.google = data.google; connectResult('Signed in with Google. Now enter your project and save.', true); renderStoryAIStatus(); return; }
  }
}
async function saveConnection(test) {
  const r = connections.current, values = {};
  $$('#connect-fields input').forEach(i => { values[i.name] = i.value.trim(); });
  const save = $('#connect-save'); save.disabled = true; connectResult(test ? 'Testing with ' + r.label + '…' : 'Saving…', true);
  try {
    const reply = await api('/api/connections/' + r.id, {method: 'PUT', body: JSON.stringify({values, test})});
    connectResult(reply.message, reply.saved);
    if (reply.saved) { toast(r.label + ' connected.'); await renderStoryAIStatus(); if (typeof loadStoryAIs === 'function') loadStoryAIs();
      setTimeout(() => $('#connect-dialog').close(), 900); }
  } catch (e) { connectResult(e.message, false); }
  finally { save.disabled = false; }
}
$('#connect-form').onsubmit = e => { e.preventDefault(); saveConnection(true); };
$('#connect-save-untested').onclick = () => saveConnection(false);
$('#close-connect').onclick = () => $('#connect-dialog').close();
$('#connect-remove').onclick = async () => {
  const r = connections.current;
  try { const reply = await api('/api/connections/' + r.id, {method: 'DELETE'}); toast(reply.message); $('#connect-dialog').close(); await renderStoryAIStatus(); if (typeof loadStoryAIs === 'function') loadStoryAIs(); }
  catch (e) { connectResult(e.message, false); }
};

// Check results as labelled rows instead of raw JSON.
function reportHtml(data) {
  if (Array.isArray(data)) return data.length ? data.map(reportHtml).join('<hr>') : '<p class="muted">Nothing recorded yet.</p>';
  if (data && typeof data === 'object') return '<dl>' + Object.entries(data).map(([k, v]) =>
    `<dt>${escape(k.replace(/_/g, ' '))}</dt><dd>${v && typeof v === 'object' ? reportHtml(v) : escape(v === null || v === '' ? '—' : String(v))}</dd>`).join('') + '</dl>';
  return `<p>${escape(String(data))}</p>`;
}
async function report(url, title) {
  const box = $('#provider-report'); box.hidden = false; box.innerHTML = `<h4>${escape(title)}</h4><p class="muted">Checking…</p>`;
  try { box.innerHTML = `<h4>${escape(title)}</h4>` + reportHtml(await api(url)); }
  catch (e) { box.innerHTML = `<h4>${escape(title)}</h4><p class="report-error">${escape(e.message)}</p>`; }
}
const label = el => el.firstChild.textContent.trim();
$$('[data-check]').forEach(el => el.onclick = () => report('/api/provider-health/' + el.dataset.check, label(el) + ' · connection'));
$$('[data-cost]').forEach(el => el.onclick = () => report('/api/provider-costs/' + el.dataset.cost, el.textContent.replace('→', '').trim()));
$('#load-usage').onclick = () => report('/api/provider-usage', 'Request history');

/* ---------- Start ---------- */
restoreDraft(); changeMode(); costEstimate(); loadStoryAIs(); loadLanguages();
const VIEWS = ['overview', 'create', 'library', 'providers'];
const hashView = () => location.hash.replace(/^#\/?/, '');
const initial = hashView();
if (VIEWS.includes(initial) && initial !== 'overview') view(initial, {scroll: false}); else animateIn($('#overview'));
addEventListener('hashchange', () => { const v = hashView(); if (VIEWS.includes(v) && v !== state.view) view(v); });
if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
refresh().catch(e => notice(e.message));
// Poll only while the tab is visible, and catch up the moment it is shown again.
setInterval(() => { if (!document.hidden) refresh().catch(() => {}); }, 5000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh().catch(() => {}); });
