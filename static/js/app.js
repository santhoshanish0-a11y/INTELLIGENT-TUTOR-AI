/* Intelligent Tutor - single-page front end (vanilla JS, no build step) */
const $ = (s, r = document) => r.querySelector(s);
const state = { user: null, token: null, meta: null, view: 'tutor', history: [], quiz: null, timerId: null };
const TITLES = { tutor: 'Ask the tutor', practice: 'Practice', mock: 'Mock test', progress: 'My progress', library: 'Library', plan: 'Study plan' };
const SUBJECT_COLORS = ['#4F5BFF', '#FFB41F', '#0FA37F', '#E8416B', '#8C6BFF', '#2AA7D6'];

const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function api(path, body) {
  const headers = { 'Content-Type': 'application/json' };
  if (state.token) headers.Authorization = 'Bearer ' + state.token;
  const res = await fetch(path, body ? { method: 'POST', headers, body: JSON.stringify(body) } : { headers });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && data.code === 'signed_out') { logout(true); throw new Error(data.error); }
  if (!res.ok) { const err = new Error(data.error || 'Something went wrong. Try again.'); err.code = data.code; throw err; }
  return data;
}

function toast(msg) {
  const t = document.createElement('div'); t.className = 'toast'; t.textContent = msg; document.body.appendChild(t);
  setTimeout(() => t.remove(), 3200);
}

/* ---------- minimal markdown renderer ---------- */
function inline(t) {
  return esc(t).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<i>$2</i>')
    // only http(s) links become clickable; the text was already HTML-escaped above
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}
function md(src) {
  const lines = src.replace(/\r/g, '').split('\n'); let out = '', i = 0;
  while (i < lines.length) {
    const l = lines[i];
    if (l.startsWith('```')) { let code = []; i++; while (i < lines.length && !lines[i].startsWith('```')) code.push(lines[i++]); i++; out += `<pre><code>${esc(code.join('\n'))}</code></pre>`; continue; }
    if (/^\s*\|.+\|\s*$/.test(l) && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1] || '')) {
      const cells = r => r.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
      let t = '<table><thead><tr>' + cells(l).map(c => `<th>${inline(c)}</th>`).join('') + '</tr></thead><tbody>'; i += 2;
      while (i < lines.length && /^\s*\|.+\|\s*$/.test(lines[i])) t += '<tr>' + cells(lines[i++]).map(c => `<td>${inline(c)}</td>`).join('') + '</tr>';
      out += t + '</tbody></table>'; continue;
    }
    const h = l.match(/^(#{1,4})\s+(.*)/); if (h) { out += `<h4>${inline(h[2])}</h4>`; i++; continue; }
    if (/^\s*[-*]\s+/.test(l)) { out += '<ul>'; while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) out += `<li>${inline(lines[i++].replace(/^\s*[-*]\s+/, ''))}</li>`; out += '</ul>'; continue; }
    if (/^\s*\d+[.)]\s+/.test(l)) { out += '<ol>'; while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) out += `<li>${inline(lines[i++].replace(/^\s*\d+[.)]\s+/, ''))}</li>`; out += '</ol>'; continue; }
    if (!l.trim()) { i++; continue; }
    let p = [l]; i++; while (i < lines.length && lines[i].trim() && !/^(```|#{1,4}\s|\s*[-*]\s|\s*\d+[.)]\s|\s*\|)/.test(lines[i])) p.push(lines[i++]);
    out += `<p>${inline(p.join(' '))}</p>`;
  }
  return out;
}

/* ---------- navigation ---------- */
function go(view) {
  if (state.timerId && view !== 'mock') { clearInterval(state.timerId); state.timerId = null; }
  state.view = view;
  // Clear every other page so element IDs (startBtn, timer, ...) are never duplicated in the DOM.
  ['practice', 'mock', 'progress', 'library', 'plan'].forEach(v => { if (v !== view) $('#view-' + v).innerHTML = ''; });
  if (state.quiz && state.quiz.kind !== view) state.quiz = null;
  document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
  $('#view-' + view).classList.remove('hidden');
  document.querySelectorAll('.nav-btn').forEach(b => { if (b.dataset.view === view) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current'); });
  $('#pageTitle').textContent = TITLES[view];
  $('#side').classList.remove('open');
  ({ practice: () => renderSetup('practice'), mock: () => renderSetup('mock'), progress: renderProgress, library: renderLibrary, plan: renderPlan })[view]?.();
  if (view === 'tutor') { $('#msgInput').focus(); }
}

/* ---------- sign in ---------- */
async function boot() {
  state.meta = await (await fetch('/api/meta')).json();
  $('#statBank').textContent = state.meta.bank_size + '+';
  const pill = $('#modePill');
  pill.className = 'pill ' + (state.meta.mode === 'ai' ? 'ai' : 'off');
  pill.textContent = state.meta.mode === 'ai' ? 'AI tutor online' : 'Offline mode';
  pill.title = state.meta.mode === 'ai' ? '' : 'Add GROQ_API_KEY to .env to answer any question';
  setAuthMode('in');
  try { localStorage.removeItem('it_user'); } catch { }          // old sign-in format, replaced by tokens
  let token = null; try { token = localStorage.getItem('it_token'); } catch { }
  if (token) {
    state.token = token;
    try { const { user } = await api('/api/me'); state.user = user; enter(); } catch { state.token = null; }
  }
}

/* ---------- sign in / sign up ---------- */
let authMode = 'in';
function setAuthMode(mode) {
  authMode = mode; const up = mode === 'up';
  $('#tabIn').setAttribute('aria-selected', !up); $('#tabUp').setAttribute('aria-selected', up);
  $('#authTitle').textContent = up ? 'Create your account' : 'Welcome back';
  $('#authSub').textContent = up ? 'Your progress is saved to your account and protected by your password.' : 'Sign in to pick up where you left off.';
  $('#authBtn').textContent = up ? 'Create account' : 'Sign in';
  $('#confirmField').classList.toggle('hidden', !up);
  $('#loginPass').autocomplete = up ? 'new-password' : 'current-password';
  $('#loginPass').placeholder = up ? 'At least 6 characters' : 'Your password';
  $('#pwHint').textContent = ''; $('#loginErr').textContent = ''; $('#loginOk').textContent = '';
}
$('#tabIn').onclick = () => setAuthMode('in');
$('#tabUp').onclick = () => setAuthMode('up');
$('#pwToggle').onclick = () => {
  const input = $('#loginPass'), show = input.type === 'password';
  input.type = show ? 'text' : 'password'; $('#loginPass2').type = input.type;
  $('#pwToggle').textContent = show ? 'Hide' : 'Show'; $('#pwToggle').setAttribute('aria-pressed', show);
  $('#pwToggle').setAttribute('aria-label', show ? 'Hide password' : 'Show password');
};
$('#loginPass').addEventListener('input', () => {
  const hint = $('#pwHint'), n = $('#loginPass').value.length;
  if (authMode !== 'up') { hint.textContent = ''; return; }
  hint.className = 'hint' + (n >= 6 ? ' ok' : '');
  hint.textContent = n === 0 ? '' : n < 6 ? `${6 - n} more character${6 - n === 1 ? '' : 's'} needed` : 'Good length';
});
$('#loginForm').addEventListener('submit', async e => {
  e.preventDefault(); const err = $('#loginErr'); err.textContent = '';
  const name = $('#loginName').value.trim(), password = $('#loginPass').value;
  if (!name) { err.textContent = 'Enter your name.'; $('#loginName').focus(); return; }
  if (!password) { err.textContent = 'Enter your password.'; $('#loginPass').focus(); return; }
  if (authMode === 'up' && password !== $('#loginPass2').value) { err.textContent = 'The two passwords do not match.'; $('#loginPass2').focus(); return; }
  const btn = $('#authBtn'); btn.disabled = true;
  try {
    if (authMode === 'up') {      // creating an account does not sign in: go to the Sign in page
      const made = await api('/api/signup', { name, password });
      $('#loginPass').value = ''; $('#loginPass2').value = '';
      setAuthMode('in');
      $('#loginName').value = made.name || name;
      $('#loginOk').textContent = 'Account created. Enter your password below to sign in.';
      $('#loginPass').focus();
      return;
    }
    const { token, user } = await api('/api/login', { name, password });
    state.token = token; state.user = user;
    try { localStorage.setItem('it_token', token); } catch { }
    $('#loginPass').value = ''; $('#loginPass2').value = ''; enter();
  } catch (ex) {
    err.textContent = ex.message;
    if (ex.code === 'no_password') setAuthMode('up'), err.textContent = ex.message;     // old account: guide them to set a password
  } finally { btn.disabled = false; }
});
async function logout(expired) {
  if (!expired && state.token) { try { await api('/api/logout', {}); } catch { } }
  try { localStorage.removeItem('it_token'); } catch { }
  state.user = null; state.token = null; state.history = []; state.quiz = null;
  if (state.timerId) { clearInterval(state.timerId); state.timerId = null; }
  $('#app').classList.add('hidden'); $('#gate').classList.remove('hidden');
  setAuthMode('in'); if (expired) $('#loginErr').textContent = 'Your session ended. Sign in again.';
}
$('#logout').onclick = () => logout();
function enter() {
  $('#gate').classList.add('hidden'); $('#app').classList.remove('hidden');
  $('#whoName').textContent = state.user.name; $('#avatar').textContent = state.user.name[0].toUpperCase();
  $('#whoExam').textContent = state.meta.exams[state.user.exam];
  renderWelcome(); refreshStreak(); go('tutor');
}
async function refreshStreak() {
  try { const d = await api('/api/dashboard'); $('#streakVal').textContent = d.streak + (d.streak === 1 ? ' day' : ' days'); $('#todayVal').textContent = `${d.today}/${d.daily_goal}`; } catch { }
}
$('#nav').addEventListener('click', e => { const b = e.target.closest('.nav-btn'); if (b) go(b.dataset.view); });
$('#menuBtn').onclick = () => $('#side').classList.toggle('open');

/* ---------- tutor chat ---------- */
const STARTERS = [
  ['Who is the current Chief Minister of Tamil Nadu?', 'Checked live on the web, with sources'],
  ['Latest SSC and RRB exam notifications', 'Current affairs from the web'],
  ['Explain compound interest', 'With a worked example and a shortcut'],
  ['What is the Preamble?', 'Key words, amendments and exam tips'],
  ['Explain photosynthesis to a Class 6 student', 'Simple words and a diagram in text'],
  ['Make me a 7 day study plan', 'Based on my weak areas'],
];
function renderWelcome() {
  $('#chat').innerHTML = `<div class="welcome"><h1>What would you like to learn today, ${esc(state.user.name)}?</h1>
    <p>Ask in your own words. I explain any topic and prepare you for government exams.</p>
    <div class="starters">${STARTERS.map(([t, s]) => `<button class="starter" data-q="${esc(t)}">${esc(t)}<small>${esc(s)}</small></button>`).join('')}</div></div>`;
  $('#chat').querySelectorAll('.starter').forEach(b => b.onclick = () => send(b.dataset.q));
}
function addMsg(role, html, actions = []) {
  const w = $('#chat .welcome'); if (w) w.remove();
  const el = document.createElement('div'); el.className = 'msg ' + (role === 'user' ? 'user' : 'bot');
  el.innerHTML = (role === 'user' ? '' : '<div class="bot-av">IT</div>') + `<div class="bubble">${html}</div>`;
  if (actions.length) {
    const box = document.createElement('div'); box.className = 'acts';
    actions.forEach(a => { const b = document.createElement('button'); b.className = 'btn btn-soft'; b.textContent = a.label; b.onclick = () => runAction(a); box.appendChild(b); });
    el.querySelector('.bubble').appendChild(box);
  }
  $('#chat').appendChild(el); $('#chat').scrollTop = $('#chat').scrollHeight; return el;
}
function runAction(a) {
  if (a.type === 'quiz') { go('practice'); if (a.subject) setTimeout(() => { const s = $('#subjectSel'); if ([...s.options].some(o => o.value === a.subject)) s.value = a.subject; }, 0); }
  else if (a.type === 'progress') go('progress');
  else if (a.type === 'library') go('library');
  else if (a.type === 'plan') go('plan');
}
async function send(text) {
  text = (text ?? $('#msgInput').value).trim(); if (!text) return;
  $('#msgInput').value = ''; autoGrow();
  addMsg('user', `<p>${esc(text)}</p>`);
  const typing = addMsg('bot', '<div class="typing"><i></i><i></i><i></i></div>');
  try {
    const r = await api('/api/chat', { message: text, level: 'Government exam', history: state.history.slice(-10) });
    state.history.push({ role: 'user', content: text }, { role: 'assistant', content: r.reply });
    typing.remove(); addMsg('bot', md(r.reply), r.actions);
    if (r.intent === 'quiz' || r.intent === 'progress') refreshStreak();
  } catch (err) { typing.remove(); addMsg('bot', `<p>${esc(err.message)}</p>`); }
}
function autoGrow() { const t = $('#msgInput'); t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 140) + 'px'; }
$('#sendBtn').onclick = () => send();
$('#msgInput').addEventListener('input', autoGrow);
$('#msgInput').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });

// voice input (Web Speech API, Chrome / Edge)
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if (!SR) $('#micBtn').classList.add('hidden');
else {
  const rec = new SR(); rec.lang = 'en-IN'; rec.interimResults = false; let on = false;
  $('#micBtn').onclick = () => { if (on) rec.stop(); else { rec.start(); } };
  rec.onstart = () => { on = true; $('#micBtn').classList.add('rec'); };
  rec.onend = () => { on = false; $('#micBtn').classList.remove('rec'); };
  rec.onresult = e => { $('#msgInput').value = e.results[0][0].transcript; autoGrow(); send(); };
}

/* ---------- practice / mock setup ---------- */
function renderSetup(kind) {
  const el = $('#view-' + kind); const exam = state.user.exam;
  const subs = state.meta.subjects[exam];
  const mock = kind === 'mock';
  el.innerHTML = `<div class="setup card">
    <h3>${mock ? 'Timed mock test' : 'Adaptive practice'}</h3>
    <p class="sub">${mock ? 'Mixed subjects, 45 seconds per question, answers revealed at the end.' : 'Questions adapt to your weak topics and difficulty level. You see the explanation after every answer.'}</p>
    <div class="form-grid">
      <div class="field"><label for="examSel">Exam</label><select id="examSel" class="sel" style="width:100%">${Object.entries(state.meta.exams).map(([k, v]) => `<option value="${k}" ${k === exam ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></div>
      <div class="field"><label for="subjectSel">Subject</label><select id="subjectSel" class="sel" style="width:100%"><option value="All">All subjects</option>${subs.map(s => `<option>${esc(s)}</option>`).join('')}</select></div>
      <div class="field"><label for="countSel">Number of questions</label><select id="countSel" class="sel" style="width:100%">${[5, 10, 15, 20, 30].map(n => `<option ${n === (mock ? 20 : 10) ? 'selected' : ''}>${n}</option>`).join('')}</select></div>
    </div>
    ${mock ? '' : `<div class="modes" id="modes">
      <button class="mode" data-m="adaptive" aria-pressed="true"><b>Adaptive</b><span>Targets your weak topics</span></button>
      <button class="mode" data-m="revision" aria-pressed="false"><b>Revision</b><span>Re-ask questions you missed</span></button>
      <button class="mode" data-m="random" aria-pressed="false"><b>Random</b><span>Any question, any topic</span></button></div>`}
    <button class="btn btn-primary" id="startBtn">${mock ? 'Start mock test' : 'Start practice'}</button><div class="err" id="setupErr"></div></div>`;
  $('#examSel').onchange = e => { $('#subjectSel').innerHTML = '<option value="All">All subjects</option>' + state.meta.subjects[e.target.value].map(s => `<option>${esc(s)}</option>`).join(''); };
  let mode = mock ? 'mock' : 'adaptive';
  $('#modes')?.addEventListener('click', e => { const b = e.target.closest('.mode'); if (!b) return; mode = b.dataset.m; $('#modes').querySelectorAll('.mode').forEach(x => x.setAttribute('aria-pressed', x === b)); });
  $('#startBtn').onclick = async () => {
    try {
      const s = await api('/api/quiz/start', { exam: $('#examSel').value, subject: $('#subjectSel').value, count: +$('#countSel').value, mode: mode === 'random' ? 'mock' : mode });
      state.quiz = { ...s, kind, idx: 0, answers: {}, startedAt: Date.now(), qStart: Date.now(), correct: 0 };
      if (mode === 'random') state.quiz.kind = 'practice';
      renderQuestion();
    } catch (err) { $('#setupErr').textContent = err.message; }
  };
}

/* ---------- question flow ---------- */
function renderQuestion() {
  const Q = state.quiz, q = Q.questions[Q.idx], el = $('#view-' + Q.kind), mock = Q.mode === 'mock' && Q.kind === 'mock';
  Q.qStart = Date.now();
  const letters = 'ABCD';
  el.innerHTML = `<div class="qwrap card">
    <div class="qhead"><span><b>Question ${Q.idx + 1}</b> of ${Q.questions.length}</span><div class="bar"><i style="width:${(Q.idx / Q.questions.length) * 100}%"></i></div>${mock ? '<span class="timer" id="timer"></span>' : ''}</div>
    <div class="tags"><span class="tag">${esc(q.subject)}</span><span class="tag">${esc(q.topic)}</span><span class="tag d${q.difficulty}">${['', 'Easy', 'Medium', 'Hard'][q.difficulty]}</span></div>
    <div class="qtext">${esc(q.question)}</div>
    <div class="opts" role="group" aria-label="Answer options">${q.options.map((o, i) => `<button class="opt" data-i="${i}"><span class="k">${letters[i]}</span><span>${esc(o)}</span></button>`).join('')}</div>
    <div id="fb"></div>
    ${mock ? `<div class="fb-actions"><button class="btn btn-ghost" id="prevBtn" ${Q.idx === 0 ? 'disabled' : ''}>Previous</button><button class="btn btn-primary" id="nextBtn">${Q.idx === Q.questions.length - 1 ? 'Review and submit' : 'Next'}</button></div>
    <div class="palette">${Q.questions.map((_, i) => `<button data-p="${i}" class="${Q.answers[Q.questions[i].id] !== undefined ? 'done' : ''} ${i === Q.idx ? 'now' : ''}" aria-label="Go to question ${i + 1}">${i + 1}</button>`).join('')}</div>` : ''}
  </div>`;
  if (mock) {
    const chosen = Q.answers[q.id]; if (chosen !== undefined) el.querySelector(`.opt[data-i="${chosen}"]`).classList.add('sel-on');
    el.querySelectorAll('.opt').forEach(b => b.onclick = () => { Q.answers[q.id] = +b.dataset.i; Q.times = Q.times || {}; Q.times[q.id] = (Q.times[q.id] || 0) + (Date.now() - Q.qStart) / 1000; renderQuestion(); });
    $('#nextBtn').onclick = () => { if (Q.idx === Q.questions.length - 1) submitMock(); else { Q.idx++; renderQuestion(); } };
    $('#prevBtn').onclick = () => { Q.idx--; renderQuestion(); };
    el.querySelectorAll('.palette button').forEach(b => b.onclick = () => { Q.idx = +b.dataset.p; renderQuestion(); });
    startTimer();
  } else {
    el.querySelectorAll('.opt').forEach(b => b.onclick = () => answerPractice(+b.dataset.i));
  }
}
async function answerPractice(choice) {
  const Q = state.quiz, q = Q.questions[Q.idx], el = $('#view-' + Q.kind);
  el.querySelectorAll('.opt').forEach(b => b.disabled = true);
  const seconds = (Date.now() - Q.qStart) / 1000;
  let r; try { r = await api('/api/quiz/answer', { session_id: Q.session_id, question_id: q.id, choice, seconds }); } catch (e) { toast(e.message); return; }
  if (r.correct) Q.correct++;
  el.querySelector(`.opt[data-i="${r.answer}"]`).classList.add('right');
  if (!r.correct) el.querySelector(`.opt[data-i="${choice}"]`).classList.add('wrong');
  const last = Q.idx === Q.questions.length - 1;
  $('#fb').innerHTML = `<div class="fb ${r.correct ? 'ok' : 'no'}"><b>${r.correct ? 'Correct' : 'Not quite'}</b>${esc(r.explanation)}
    <div class="fb-actions">${r.correct ? '' : '<button class="btn btn-soft" id="deepBtn">Explain in depth</button>'}<button class="btn btn-primary" id="contBtn">${last ? 'See results' : 'Next question'}</button></div><div id="deep"></div></div>`;
  $('#contBtn').onclick = () => { if (last) finishQuiz(); else { Q.idx++; renderQuestion(); } };
  $('#deepBtn')?.addEventListener('click', async e => {
    e.target.disabled = true; e.target.textContent = 'Thinking...';
    try { const d = await api('/api/quiz/review', { question_id: q.id, choice }); $('#deep').innerHTML = `<div class="deep bubble">${md(d.reply)}</div>`; e.target.remove(); }
    catch (err) { toast(err.message); e.target.disabled = false; e.target.textContent = 'Explain in depth'; }
  });
  $('#contBtn').scrollIntoView({ block: 'nearest', behavior: 'smooth' }); refreshStreak();
}
function startTimer() {
  const Q = state.quiz; if (state.timerId) clearInterval(state.timerId);
  if (Q.endAt === undefined) Q.endAt = Date.now() + Q.time_limit * 1000;
  const tick = () => {
    const left = Math.max(0, Math.round((Q.endAt - Date.now()) / 1000)); const t = $('#timer');
    if (t) { t.textContent = `${String(Math.floor(left / 60)).padStart(2, '0')}:${String(left % 60).padStart(2, '0')}`; t.classList.toggle('low', left <= 60); }
    if (left <= 0) { clearInterval(state.timerId); toast('Time is up. Submitting your test.'); submitMock(); }
  };
  tick(); state.timerId = setInterval(tick, 1000);
}
async function submitMock() {
  const Q = state.quiz; clearInterval(state.timerId); state.timerId = null;
  for (const q of Q.questions) {
    const c = Q.answers[q.id]; if (c === undefined) continue;
    try { const r = await api('/api/quiz/answer', { session_id: Q.session_id, question_id: q.id, choice: c, seconds: Q.times?.[q.id] || 0 }); Q.review = Q.review || {}; Q.review[q.id] = r; } catch { }
  }
  finishQuiz();
}
async function finishQuiz() {
  const Q = state.quiz, el = $('#view-' + Q.kind);
  const s = await api('/api/quiz/finish', { session_id: Q.session_id });
  const skipped = Q.questions.length - s.total;
  const C = 2 * Math.PI * 54, off = C * (1 - s.percent / 100);
  const color = s.percent >= 75 ? '#0FA37F' : s.percent >= 50 ? '#FFB41F' : '#E8416B';
  const msg = s.percent >= 75 ? 'Excellent work. Keep this pace.' : s.percent >= 50 ? 'Good progress. A little more focus on the weak topics will lift your score.' : 'Every attempt maps your gaps. Revise the topics below and try again.';
  el.innerHTML = `<div class="result"><div class="card score-top">
    <svg class="ring" viewBox="0 0 120 120"><circle cx="60" cy="60" r="54" fill="none" stroke="#E3E7F4" stroke-width="11"/><circle cx="60" cy="60" r="54" fill="none" stroke="${color}" stroke-width="11" stroke-linecap="round" stroke-dasharray="${C}" stroke-dashoffset="${off}" transform="rotate(-90 60 60)"/><text x="60" y="68" text-anchor="middle" font-size="26" fill="#1B2145">${s.percent}%</text></svg>
    <div><h3>${s.score} of ${Q.questions.length} correct</h3><p>${msg}${skipped > 0 ? ` You skipped ${skipped}.` : ''}</p>
    <div class="fb-actions"><button class="btn btn-primary" id="againBtn">Try again</button><button class="btn btn-ghost" id="progBtn">View progress</button></div></div></div>
    <div class="card"><h3>Topic breakdown</h3>${s.breakdown.map(b => { const p = Math.round(100 * b.correct / b.total); return `<div class="topic-row"><div>${esc(b.topic)}<small>${esc(b.subject)}</small></div><div class="meter"><i class="${p >= 75 ? 'st-strong' : p >= 50 ? 'st-developing' : 'st-weak'}" style="width:${p}%"></i></div><div class="pct">${b.correct}/${b.total}</div></div>`; }).join('') || '<div class="empty">No answers were submitted.</div>'}</div>
    ${Q.review ? `<div class="card"><h3>Answer review</h3>${Q.questions.map((q, i) => { const r = Q.review[q.id]; if (!r) return ''; return `<div class="rec"><div class="ic" style="background:${r.correct ? 'var(--teal-l)' : 'var(--rose-l)'};color:${r.correct ? 'var(--teal)' : 'var(--rose)'}">${i + 1}</div><div><b>${esc(q.question)}</b><small>Your answer: ${esc(q.options[Q.answers[q.id]])}${r.correct ? '' : ' | Correct: ' + esc(q.options[r.answer])}</small><small>${esc(r.explanation)}</small></div></div>`; }).join('')}</div>` : ''}
    ${s.recommendations.length ? `<div class="card"><h3>Recommended next</h3>${recHtml(s.recommendations)}</div>` : ''}</div>`;
  $('#againBtn').onclick = () => renderSetup(Q.kind); $('#progBtn').onclick = () => go('progress'); state.quiz = null; refreshStreak();
}
function recHtml(list) {
  return list.map(r => `<div class="rec"><div class="ic"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2V5z"/></svg></div><div>${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a>` : `<b>${esc(r.title)}</b>`}<small>${esc(r.type)}${r.reason ? ' | ' + esc(r.reason) : ''}</small>${r.note ? `<small>${esc(r.note)}</small>` : ''}</div></div>`).join('');
}

/* ---------- progress dashboard ---------- */
function radar(subjects) {
  const n = subjects.length; if (n < 3) return '<div class="empty">Attempt questions from at least 3 subjects to see your mastery map.</div>';
  const cx = 150, cy = 150, R = 105, pt = (i, v) => { const a = -Math.PI / 2 + i * 2 * Math.PI / n; return [cx + Math.cos(a) * R * v, cy + Math.sin(a) * R * v]; };
  const rings = [0.25, 0.5, 0.75, 1].map(v => `<polygon points="${subjects.map((_, i) => pt(i, v).join(',')).join(' ')}" fill="none" stroke="#E3E7F4"/>`).join('');
  const axes = subjects.map((_, i) => { const [x, y] = pt(i, 1); return `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#E3E7F4"/>`; }).join('');
  const poly = subjects.map((s, i) => pt(i, Math.max(.04, s.mastery)).join(',')).join(' ');
  const dots = subjects.map((s, i) => { const [x, y] = pt(i, Math.max(.04, s.mastery)); return `<circle cx="${x}" cy="${y}" r="4.5" fill="${SUBJECT_COLORS[i % 6]}" stroke="#fff" stroke-width="2"/>`; }).join('');
  const labels = subjects.map((s, i) => { const [x, y] = pt(i, 1.2); const a = Math.cos(-Math.PI / 2 + i * 2 * Math.PI / n); return `<text x="${x}" y="${y}" font-size="10.5" fill="#6A7196" text-anchor="${a > .3 ? 'start' : a < -.3 ? 'end' : 'middle'}">${esc(s.subject.length > 14 ? s.subject.split(' ')[0] : s.subject)}</text>`; }).join('');
  return `<svg viewBox="0 0 300 300" style="width:100%;max-width:360px;display:block;margin:auto" role="img" aria-label="Mastery by subject">${rings}${axes}<polygon points="${poly}" fill="rgba(79,91,255,.18)" stroke="#4F5BFF" stroke-width="2.2"/>${dots}${labels}</svg>`;
}
function trend(history) {
  if (history.length < 2) return '<div class="empty">Finish two quizzes to see your score trend.</div>';
  const W = 420, H = 150, p = 24, pts = history.map((h, i) => [p + i * (W - 2 * p) / (history.length - 1), H - p - (h.total ? h.score / h.total : 0) * (H - 2 * p)]);
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%" role="img" aria-label="Score trend"><line x1="${p}" y1="${H - p}" x2="${W - p}" y2="${H - p}" stroke="#E3E7F4"/><polyline points="${pts.map(q => q.join(',')).join(' ')}" fill="none" stroke="#4F5BFF" stroke-width="2.5" stroke-linejoin="round"/>${pts.map((q, i) => `<circle cx="${q[0]}" cy="${q[1]}" r="4" fill="#4F5BFF"/><text x="${q[0]}" y="${q[1] - 9}" font-size="10" text-anchor="middle" fill="#6A7196">${Math.round(100 * history[i].score / (history[i].total || 1))}%</text>`).join('')}</svg>`;
}
async function renderProgress() {
  const el = $('#view-progress'); el.innerHTML = '<div class="empty">Loading your dashboard...</div>';
  let d; try { d = await api('/api/dashboard'); } catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  if (!d.questions_attempted) { el.innerHTML = `<div class="card empty"><b>No data yet</b>Answer a few practice questions and your strengths, weak areas and recommendations will appear here.<div style="margin-top:16px"><button class="btn btn-primary" onclick="go('practice')">Start practice</button></div></div>`; return; }
  const row = t => `<div class="topic-row"><div>${esc(t.topic)}<small>${esc(t.subject)} | ${t.attempts} attempts</small></div><div class="meter" title="${t.status}"><i class="st-${t.status}" style="width:${Math.round(t.mastery * 100)}%"></i></div><div class="pct">${t.accuracy}%</div></div>`;
  el.innerHTML = `<div class="kpis">
    <div class="kpi"><b>${d.questions_attempted}</b><span>Questions answered</span></div>
    <div class="kpi"><b>${d.accuracy}%</b><span>Overall accuracy</span></div>
    <div class="kpi"><b>${d.streak}</b><span>Day streak</span></div>
    <div class="kpi"><b>${d.today}/${d.daily_goal}</b><span>Today's goal</span></div></div>
    <div class="two"><div class="card"><h3>Mastery map</h3>${radar(d.subjects)}</div>
    <div class="card"><h3>Weak areas to fix first</h3>${d.weak.length ? d.weak.map(row).join('') : '<div class="empty"><b>No weak topics</b>Keep practising across more topics to find gaps.</div>'}
    <div style="margin-top:14px"><button class="btn btn-soft" id="fixBtn">Practise weak topics</button></div></div></div>
    <div class="two"><div class="card"><h3>Score trend</h3>${trend(d.history)}</div>
    <div class="card"><h3>Recommended for you</h3>${d.recommendations.length ? recHtml(d.recommendations) : '<div class="empty">Recommendations appear once a weak topic is detected.</div>'}</div></div>
    <div class="card" style="margin-top:20px"><h3>All topics</h3>${d.topics.map(row).join('')}</div>`;
  $('#fixBtn').onclick = () => go('practice');
}

/* ---------- library & plan ---------- */
async function renderLibrary() {
  const el = $('#view-library'); const data = await (await fetch('/api/materials')).json();
  const exam = state.user.exam, allowed = new Set(state.meta.subjects[exam]);
  el.innerHTML = `<div class="lib">${data.filter(m => allowed.has(m.subject)).map(m => `<div class="card"><h3>${esc(m.subject)}</h3>${recHtml(m.items)}</div>`).join('')}</div>`;
}
async function renderPlan() {
  const el = $('#view-plan');
  el.innerHTML = `<div class="card plan-head"><div><h3>Personal study plan</h3><p style="color:var(--muted)">Built from your weak topics. Regenerate after every quiz.</p></div>
    <select class="sel" id="daysSel" style="margin-left:auto">${[7, 14, 30].map(n => `<option value="${n}">${n} days</option>`).join('')}</select><button class="btn btn-primary" id="genBtn">Generate plan</button></div><div id="planOut"></div>`;
  const gen = async () => {
    const { plan } = await api('/api/plan?days=' + $('#daysSel').value);
    $('#planOut').innerHTML = `<div class="plan">${plan.map(p => `<div class="card"><h4>Day ${p.day}: ${esc(p.focus)}</h4><ul>${p.tasks.map(t => `<li>${esc(t)}</li>`).join('')}</ul></div>`).join('')}</div>`;
  };
  $('#genBtn').onclick = gen; gen();
}

boot();