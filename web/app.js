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
function notice(message) { $('#notice').textContent = message; $('#notice').hidden = !message; }
function toast(message) {
  const el = $('#toast'); el.hidden = true; void el.offsetWidth; // restart the entrance animation
  el.textContent = message; el.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => el.hidden = true, 4200);
}
async function request(url, options = {}) {
  const response = await fetch(url, {...options, headers: {...(options.body ? {'Content-Type': 'application/json'} : {}), ...options.headers}});
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || `Request failed (${response.status})`));
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
const templates = {
  story: 'বৃষ্টির বিকেলে মীরা একটি কাগজের নৌকা বানিয়ে ছোট ভাইকে দিল। নৌকা জলে ভেসে গেলে তারা আনন্দে হাততালি দেয়। এই গল্প নিয়ে একটি কোমল cinematic animation বানাও।',
  brand: 'Fresh Tea ব্র্যান্ডের জন্য একটি cinematic বিজ্ঞাপন বানাও। চা বাগান, সবুজ পাতা এবং গরম চায়ের কাপ দেখাও। শেষে লিখবে “প্রতিটি চুমুকে সতেজতা”।',
  explainer: 'চা পাতা থেকে এক কাপ চা কীভাবে তৈরি হয় তা সহজভাবে বোঝাও। পাতা সংগ্রহ, প্রক্রিয়াজাতকরণ এবং চা বানানোর ধাপ দেখাও।'
};
$$('[data-template]').forEach(el => el.addEventListener('click', () => {
  $('#story').value = templates[el.dataset.template]; count(); view('create'); $('#story').focus();
}));
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
      <div><span>${date ? escape(new Date(parseDate(date)).toLocaleDateString('en-GB', {month: 'short', day: 'numeric', timeZone: 'Asia/Dhaka'})) : 'Saved project'}</span>
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
    && `${j.title || ''} ${j.id} ${j.run || ''}`.toLowerCase().includes(term));
  $('#all-projects').innerHTML = filtered.map(card).join('') || '<div class="empty"><span>▦</span><h3>No projects here yet.</h3><p>Try a different filter or start a new story.</p></div>';
  applyStyles();
  $$('.project-card').forEach(el => el.addEventListener('click', () => openProject(state.jobs.find(j => j.key === el.dataset.job))));
  $$('[data-go]').forEach(el => el.addEventListener('click', () => view(el.dataset.go)));
}
// Avoid re-rendering cards (and replaying their entrance) when nothing visible changed.
const signature = jobs => JSON.stringify(jobs.map(j => [j.key, j.state, j.stage, j.thumb, j.title, (j.pipeline?.completed || []).length]));

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
    $('#connection').classList.toggle('off', !connected);
    $('#connection').innerHTML = '<i></i>' + (connected ? 'Studio connected' : results[0].status === 'fulfilled' ? 'Local studio · API offline' : 'Connection interrupted');
    if (changed) renderProjects();
    if (state.selected) {
      const updated = jobs.find(j => j.key === state.selected.key);
      if (updated) {
        const stateChanged = state.selected.state !== updated.state, stageChanged = state.selected.stage !== updated.stage;
        state.selected = updated;
        if (stateChanged) { await openProject(updated); return; }
        $('#job-state').textContent = (labels[updated.state] || updated.state) + (updated.error ? ' · ' + updated.error : '');
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
$$('[data-filter]').forEach(el => el.addEventListener('click', () => {
  state.filter = el.dataset.filter; $$('[data-filter]').forEach(b => b.classList.toggle('active', b === el)); renderProjects();
}));

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

function changeMode() {
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
    await refresh(); view('library'); toast('Your story is in production.');
    const j = state.jobs.find(j => j.id === result.id); if (j) openProject(j);
  } catch (e) { notice(e.message); window.scrollTo({top: 0, behavior: 'smooth'}); }
  finally { button.disabled = false; }
});
$('#create-form').elements.namedItem('language').addEventListener('change', event => {
  $('#create-form').elements.namedItem('voice').value = event.target.value === 'English' ? 'en-US-AriaNeural' : 'bn-BD-NabanitaNeural';
});

/* ---------- Project dialog ---------- */
async function loadLog(job) {
  try { const pre = $('#job-log'); const atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
    pre.textContent = (await api(`/local/jobs/${job.id}/log`)).log; if (atEnd) pre.scrollTop = pre.scrollHeight;
  } catch (e) { $('#job-log').textContent = e.message; }
}
async function openProject(job) {
  if (!job) return;
  state.selected = job;
  $('#preview-title').textContent = job.title || job.run || 'Your story';
  $('#job-state').textContent = (labels[job.state] || job.state) + (job.error ? ' · ' + job.error : '');
  const video = $('#video-preview'); video.pause(); video.removeAttribute('src'); video.hidden = true;
  // Show a real frame of the film instead of a black box before playback.
  if (job.local && job.thumb) video.poster = `/local/jobs/${encodeURIComponent(job.id)}/artifact?file=${encodeURIComponent(job.thumb)}`;
  else video.removeAttribute('poster');
  video.load();
  $('#download-video').hidden = true; $('#download-srt').hidden = true; $('#publish-section').hidden = true; $('#job-action').hidden = true;
  $('#job-log').textContent = ''; $('#cinematic-review').hidden = true; $('#logs-block').hidden = !job.local;
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
$('#close-dialog').onclick = () => { $('#video-preview').pause(); $('#preview-dialog').close(); state.selected = null; };
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
    FAILED: 'The current stage failed. Check the production log, fix the cause, then retry the stage.'};
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
const selectFields = {video_provider: ['Video provider', 'muse-video.com', 'runway'], video_fallback: ['Video backup', 'muse-video.com', 'runway'],
  runway_video_model: ['Runway model', 'gen4.5', 'kling3.0_standard', 'kling3.0_pro'], image_provider: ['Illustration provider', 'openai', 'vertex', 'off'],
  tts_provider: ['Voice provider', 'openai', 'elevenlabs']};
const textFields = {image_model: 'Illustration model', tts_model: 'Voice model', tts_voice: 'Voice ID', tts_fallback_model: 'Backup voice model', tts_fallback_voice: 'Backup voice ID'};
$('#provider-fields').innerHTML = Object.entries(selectFields).map(([name, [label, ...options]]) => `<label>${label}<select name="${name}"><option value="">Use server settings</option>${options.map(v => `<option>${v}</option>`).join('')}</select></label>`).join('')
  + Object.entries(textFields).map(([name, label]) => `<label>${label}<input name="${name}" maxlength="200" placeholder="Use server settings"></label>`).join('')
  + '<label>Story budget / job (USD)<input name="story_budget_usd" type="number" min="0" step="any" placeholder="Optional"></label>';
$('#load-defaults').onclick = async () => {
  try {
    const data = await api('/api/providers');
    for (const [key, value] of Object.entries(data)) { const input = $('#provider-form').elements.namedItem(key); if (input) input.value = value == null ? '' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value); }
    toast('Saved defaults loaded.');
  } catch (e) { notice(e.message); }
};
$('#provider-form').onsubmit = async e => {
  e.preventDefault();
  try {
    const form = new FormData(e.currentTarget), payload = {};
    for (const [key, value] of form) payload[key] = value.trim() ? (key === 'story_routing' ? JSON.parse(value) : key === 'story_budget_usd' ? Number(value) : value.trim()) : null;
    await api('/api/providers', {method: 'PUT', body: JSON.stringify(payload)}); toast('Provider preferences saved.');
  } catch (e) { notice(e.message); }
};
async function report(url) {
  try { $('#provider-report').textContent = 'Checking…'; $('#provider-report').textContent = JSON.stringify(await api(url), null, 2); }
  catch (e) { $('#provider-report').textContent = e.message; }
}
$$('[data-check]').forEach(el => el.onclick = () => report('/api/provider-health/' + el.dataset.check));
$$('[data-cost]').forEach(el => el.onclick = () => report('/api/provider-costs/' + el.dataset.cost));
$('#load-usage').onclick = () => report('/api/provider-usage');

/* ---------- Start ---------- */
changeMode(); costEstimate(); loadStoryAIs();
const VIEWS = ['overview', 'create', 'library', 'providers'];
const hashView = () => location.hash.replace(/^#\/?/, '');
const initial = hashView();
if (VIEWS.includes(initial) && initial !== 'overview') view(initial, {scroll: false}); else animateIn($('#overview'));
addEventListener('hashchange', () => { const v = hashView(); if (VIEWS.includes(v) && v !== state.view) view(v); });
if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
refresh().catch(e => notice(e.message));
setInterval(() => refresh().catch(() => {}), 5000);
