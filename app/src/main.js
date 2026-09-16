const DATA = {
  "49797": {
    code: "49797 · Advanced AI for Industry and Society",
    sessions: [
      { id: "s1", num: "#6", title: "Grounding and Citation in RAG Systems", date: "Sep 12", duration: "48:12" },
      { id: "s2", num: "#5", title: "Hybrid Retrieval: BM25 + Vector Search", date: "Sep 10", duration: "51:40" },
      { id: "s3", num: "#4", title: "Chunking Strategies for Long Documents", date: "Sep  8", duration: "44:55" },
      { id: "s4", num: "#3", title: "Evaluating LLM Systems in the Wild", date: "Sep  3", duration: "49:20" }
    ],
    qa: {
      q: "What's the difference between retrieval precision@k and answer groundedness?",
      a: [
        "Precision@k measures whether the chunks a retriever returns are relevant to the query — it says nothing about what the model does with them once they're in context.",
        "Groundedness measures the generated answer itself: whether every factual claim in it is actually supported by the retrieved source. A retriever can score well on precision@k and the model can still hallucinate a claim the sources don't back — that's why SSB grades them as two separate metrics rather than assuming one implies the other."
      ],
      sources: ["Lecture 6 · 14:22", "Lecture 5 · 08:05", "Course reader — Ch. 4"]
    },
    session: {
      s1: {
        transcript: [
          ["00:00", "Today we're separating two things people conflate: retrieval quality and answer groundedness."],
          ["02:14", "Precision at k just asks — of the k chunks you retrieved, how many were actually relevant."],
          ["07:41", "Groundedness asks a harder question: does every claim in the generated answer trace back to a chunk."],
          ["14:22", "A system can nail precision@k and still hallucinate at generation time. Those are independent failure modes.", true],
          ["21:03", "This is why SSB grades artifact groundedness separately from answer groundedness — a wrong mock-test question is worse than no mock test."]
        ],
        notes: "- precision@k ≠ groundedness, they fail independently\n- artifact groundedness graded separately (mock test can be \"worse than nothing\")\n- ask: does hybrid BM25+vector change precision@k meaningfully vs. vector-only?"
      }
    },
    mocktest: [
      { q: "Why can a retriever with high precision@k still produce an ungrounded answer?", a: "Precision@k only measures whether retrieved chunks are relevant to the query. Generation is a separate step — the model can still add, misstate, or over-extrapolate beyond what those chunks support. The two failure modes are independent, so both need their own metric.", src: "Lecture 6 · 14:22" },
      { q: "Why does SSB treat artifact groundedness as a separate metric from answer groundedness?", a: "A wrong Q&A answer is visibly wrong and the student can push back immediately. A hallucinated mock-test question isn't caught until the exam — the student studies the wrong thing and finds out too late. That asymmetry is why artifacts get their own bar.", src: "Design spec §8" },
      { q: "What does hybrid BM25 + vector retrieval add over vector-only search?", a: "BM25 catches exact lexical matches — course-specific terms, acronyms, function names — that a dense embedding can blur together. Vector search catches paraphrase and conceptual similarity BM25 misses. Combined, they cover both failure modes of the other.", src: "Lecture 5 · 08:05" }
    ],
    cards: [
      { front: "What does \"grounded\" mean for an SSB answer?", back: "Every factual claim traces to a specific indexed page, file, or transcript segment — if the material doesn't support it, SSB says so instead of guessing." },
      { front: "Answer-first vs. Socratic mode — what's the default?", back: "Answer-first is the default, since that's what students want under time pressure. Socratic mode (guiding questions before the answer) is an opt-in toggle for exam prep." },
      { front: "Why is a shared vector store risky for lecture recordings?", back: "A filter-bug in a shared corpus is a cross-student data leak. Physical per-student isolation turns the same bug into an empty result instead." }
    ],
    slides: [
      { n: "01", title: "RAG Pipeline Overview", bullets: ["Ingest → chunk → embed → index", "Retrieve behind a single interface", "Generate with inline citations"] },
      { n: "02", title: "Chunking Strategies", bullets: ["Fixed-size vs. semantic boundaries", "Image-heavy PDFs need a VLM/OCR pass"] },
      { n: "03", title: "Hybrid Retrieval", bullets: ["BM25 for lexical exact-match", "Vector search for paraphrase", "Merge + re-rank before generation"] },
      { n: "04", title: "Evaluating Groundedness", bullets: ["Citation groundedness rate", "Precision@k vs. answer groundedness", "Graded separately for artifacts"] }
    ],
    mindmap: { center: "RAG System", nodes: ["Ingestion", "Retrieval", "Generation", "Evaluation"] },
    assignments: [
      {
        id: "a1",
        title: "HW3 — RAG Evaluation Report",
        due: "Sep 19",
        weight: "15% of grade",
        status: "Not started",
        prompt: "Build a small evaluation harness for the retrieval pipeline from Lecture 5–6. Given the provided question set and indexed corpus, report retrieval precision@k for k = 3 and k = 5, and separately grade answer groundedness on the same questions using the rubric in the course reader. Submit your harness code, the raw scores, and a one-page write-up comparing what precision@k and groundedness each did — and didn't — catch.",
        explain: {
          breakdown: [
            "Two deliverables, not one: a precision@k measurement on retrieval alone, and a groundedness grade on the generated answers — done separately, not folded into a single score.",
            "The write-up is the actual point of the assignment — it's asking you to find a case where the two metrics disagree, not just report two numbers.",
            "\"Rubric from the course reader\" means you need Ch. 4 open while grading groundedness, not eyeballing it."
          ],
          tips: [
            { text: "Lecture 6 covers exactly why these two metrics can diverge — start there before writing the harness.", src: "Lecture 6 · 14:22" },
            { text: "Lecture 5 walks through the hybrid BM25 + vector setup you'll likely reuse for the retrieval half.", src: "Lecture 5 · 08:05" },
            { text: "The groundedness grading rubric itself lives in the reader, not the lectures.", src: "Course reader — Ch. 4" }
          ]
        }
      }
    ]
  },
  "18654": {
    code: "18654 · Software Testing and Operations",
    sessions: [
      { id: "t1", num: "#4", title: "Flaky Test Detection and Quarantine", date: "Sep 11", duration: "39:18" },
      { id: "t2", num: "#3", title: "Coverage Metrics: What They Don't Tell You", date: "Sep  9", duration: "42:02" },
      { id: "t3", num: "#2", title: "CI Pipeline Design and Fast Feedback", date: "Sep  4", duration: "37:47" }
    ],
    qa: {
      q: "How do you tell a flaky test apart from a real regression?",
      a: [
        "A regression fails deterministically against a specific commit — re-running it against the same code produces the same failure. A flaky test's pass/fail outcome changes across runs with no code change at all, usually from timing, shared state, or ordering dependencies.",
        "The practical test: re-run the failing test in isolation, several times, against an unchanged commit. Consistent failure points to a real regression; inconsistent outcomes point to flakiness — and the fix is different in each case: bisect for a regression, find the race condition for flakiness."
      ],
      sources: ["Lecture 4 · 11:30", "Lecture 2 · 22:10"]
    },
    session: {
      t1: {
        transcript: [
          ["00:00", "Flaky tests erode trust in the suite faster than almost anything else — people stop believing red means broken."],
          ["04:55", "Quarantine isn't the same as ignoring. A quarantined test still runs, it just can't block the pipeline."],
          ["11:30", "The tell: re-run it in isolation against an unchanged commit. If the outcome changes, it's flaky, not a regression.", true],
          ["18:20", "Most flakiness traces to shared state between tests or unmocked wall-clock time — check those two first."]
        ],
        notes: "- quarantine ≠ ignore — still runs, doesn't block\n- re-run in isolation on unchanged commit = the diagnostic\n- check shared state + wall-clock time first"
      }
    },
    mocktest: [
      { q: "What's the operational difference between quarantining a flaky test and deleting it?", a: "A quarantined test keeps running and reporting, it just can't block the pipeline — so you still get signal and a paper trail. Deleting it removes that coverage entirely and the underlying race condition (or real bug) goes unmonitored.", src: "Lecture 4 · 04:55" },
      { q: "Give the standard diagnostic for flaky vs. regression.", a: "Re-run the failing test in isolation, multiple times, against an unchanged commit. A real regression fails consistently; a flaky test's outcome varies with no code change.", src: "Lecture 4 · 11:30" }
    ],
    cards: [
      { front: "Two most common root causes of test flakiness?", back: "Shared state leaking between tests, and unmocked wall-clock/timing dependencies." },
      { front: "What does \"quarantine\" mean for a flaky test in CI?", back: "It keeps running and reporting results, but is excluded from blocking the pipeline until it's fixed." }
    ],
    slides: [
      { n: "01", title: "CI Feedback Loops", bullets: ["Fast path vs. full suite split", "Fail fast on the signal that matters"] },
      { n: "02", title: "Flaky Test Diagnosis", bullets: ["Re-run isolated on unchanged commit", "Shared state + wall-clock are top causes"] },
      { n: "03", title: "Coverage Metrics", bullets: ["Line coverage says nothing about assertion quality", "Mutation testing as a stronger signal"] }
    ],
    mindmap: { center: "Test Suite Health", nodes: ["Flaky Detection", "Coverage", "CI Pipeline", "Postmortems"] },
    assignments: [
      {
        id: "b1",
        title: "Lab 2 — Flaky Test Triage",
        due: "Sep 18",
        weight: "10% of grade",
        status: "Not started",
        prompt: "You're given a repo with a test suite where 4 of 60 tests fail intermittently. Pick 3 of the 4, diagnose the root cause of each — shared state, timing, or ordering — and propose a fix for each (a code diff or a written patch description is fine). Submit a short report: one paragraph per test covering diagnosis, evidence, and fix.",
        explain: {
          breakdown: [
            "Diagnosis before fix, and it wants evidence — a repro or re-run log, not just a guess at the cause.",
            "Three categories to sort into: shared state, timing, ordering. Each of your three picks should land cleanly in one.",
            "The fix can be a written description, not necessarily working code — the prompt explicitly allows \"a diff or a written patch description.\""
          ],
          tips: [
            { text: "This is the exact diagnostic covered here: re-run the failing test in isolation against an unchanged commit.", src: "Lecture 4 · 11:30" },
            { text: "Shared state and unmocked wall-clock timing are named as the two most common root causes — check those first.", src: "Lecture 4 · 18:20" }
          ]
        }
      }
    ]
  }
};

const WAVE = [8,14,22,16,30,26,12,20,34,28,18,10,24,32,20,14,8,18,26,30,22,12,16,28,34,20,10,24,30,18,14,22,26,16,8,20,32,24,12,18,28,34,20,10,16,24,30,22];

let state = { course: "49797", view: "home", session: null, artifact: "mocktest", assignment: null, explainOpen: false };

function el(tag, cls, html){ const e = document.createElement(tag); if(cls) e.className = cls; if(html !== undefined) e.innerHTML = html; return e; }

function renderCourseNav(){
  const wrap = document.getElementById('course-nav');
  wrap.innerHTML = '';
  Object.keys(DATA).forEach(code => {
    const b = el('button', 'course-btn' + (code === state.course ? ' active' : ''));
    b.innerHTML = '<span class="dot"></span>' + code;
    b.onclick = () => { state.course = code; state.view = 'home'; renderAll(); };
    wrap.appendChild(b);
  });
}

function renderSessionNav(){
  const wrap = document.getElementById('session-nav');
  wrap.innerHTML = '';
  DATA[state.course].sessions.forEach(s => {
    const b = el('button', 'session-btn' + (state.session === s.id ? ' active' : ''));
    b.innerHTML = 'Class ' + s.num + '<span class="sdate">' + s.date + '</span>';
    b.onclick = () => openSession(s.id);
    wrap.appendChild(b);
  });
}

function renderTopbar(){
  const c = DATA[state.course];
  document.getElementById('course-title').textContent = state.course;
  document.getElementById('course-code').textContent = c.code;
}

function renderQaThread(){
  const c = DATA[state.course];
  const wrap = document.getElementById('qa-thread');
  wrap.innerHTML = '';
  wrap.appendChild(el('div', 'qa-q', c.qa.q));
  const a = el('div', 'qa-a');
  c.qa.a.forEach(p => a.appendChild(el('p', null, p)));
  const src = el('div', 'qa-sources', '<span>Sources</span>');
  c.qa.sources.forEach(s => { const chip = el('span', 'cite', s); src.appendChild(chip); });
  a.appendChild(src);
  wrap.appendChild(a);
}

const ARTIFACT_TYPES = [
  { key: 'mocktest', lbl: 'Mock Test', sub: 'Q&A, cited' },
  { key: 'mindmap', lbl: 'Mindmap', sub: 'Concept graph' },
  { key: 'cards', lbl: 'Flashcards', sub: 'Spaced repeat' },
  { key: 'slides', lbl: 'Slides', sub: 'Condensed deck' }
];

function renderArtifactRow(){
  const wrap = document.getElementById('artifact-row');
  wrap.innerHTML = '';
  ARTIFACT_TYPES.forEach(t => {
    const b = el('button', 'artifact-btn');
    b.innerHTML = '<span class="lbl">' + t.lbl + '</span><span class="sub">' + t.sub + '</span>';
    b.onclick = () => openArtifact(t.key);
    wrap.appendChild(b);
  });
}

function renderSessionList(){
  const wrap = document.getElementById('session-list');
  wrap.innerHTML = '';
  DATA[state.course].sessions.forEach(s => {
    const b = el('button', 'session-card');
    b.innerHTML = '<span class="num mono">' + s.num + '</span>' +
      '<span class="meta"><div class="ttl">' + s.title + '</div><div class="dt">' + s.date + ' · ' + s.duration + '</div></span>' +
      '<span class="go">›</span>';
    b.onclick = () => openSession(s.id);
    wrap.appendChild(b);
  });
}

function renderNextAssignment(){
  const a = DATA[state.course].assignments[0];
  const card = document.getElementById('next-assign-card');
  card.innerHTML = '<span class="main"><div class="ttl">' + a.title + '</div><div class="crs">' + state.course + ' · ' + a.status + '</div></span>' +
    '<span class="pill pill-ochre">Due ' + a.due + '</span><span class="go">›</span>';
  card.onclick = () => openAssignment(a.id);
}

function openSession(id){
  state.session = id; state.view = 'session';
  renderAll();
}

function openArtifact(type){
  state.artifact = type; state.view = 'artifact';
  renderAll();
}

function openAssignment(id){
  state.assignment = id; state.view = 'assignment'; state.explainOpen = false;
  renderAll();
}

function renderSessionView(){
  const c = DATA[state.course];
  const meta = c.sessions.find(s => s.id === state.session);
  const detail = c.session[state.session] || Object.values(c.session)[0];
  document.getElementById('sess-title').textContent = 'Class ' + meta.num + ' — ' + meta.title;
  document.getElementById('sess-date').textContent = meta.date;
  document.getElementById('sess-duration').textContent = '15:04 / ' + meta.duration;

  const wf = document.getElementById('waveform');
  wf.innerHTML = '';
  WAVE.forEach((h, i) => {
    const bar = el('i');
    bar.style.height = h + 'px';
    if (i < 15) bar.classList.add('played');
    wf.appendChild(bar);
  });

  const tr = document.getElementById('transcript');
  tr.innerHTML = '';
  detail.transcript.forEach(row => {
    const line = el('div', 'tline' + (row[2] ? ' current' : ''));
    line.innerHTML = '<span class="tc mono">' + row[0] + '</span><span>' + row[1] + '</span>';
    tr.appendChild(line);
  });

  document.getElementById('notes-area').textContent = detail.notes;
}

function renderArtifactView(){
  const c = DATA[state.course];
  const t = ARTIFACT_TYPES.find(x => x.key === state.artifact);
  document.getElementById('art-title').textContent = t.lbl + ' — ' + state.course;

  const tabs = document.getElementById('art-tabs');
  tabs.innerHTML = '';
  ARTIFACT_TYPES.forEach(x => {
    const b = el('button', 'tab' + (x.key === state.artifact ? ' active' : ''), x.lbl);
    b.onclick = () => openArtifact(x.key);
    tabs.appendChild(b);
  });

  ['mocktest','mindmap','cards','slides'].forEach(k => document.getElementById('art-' + k).hidden = (k !== state.artifact));

  if (state.artifact === 'mocktest') {
    const box = document.getElementById('art-mocktest');
    box.innerHTML = '';
    document.getElementById('art-ground').textContent = c.mocktest.length + ' / ' + c.mocktest.length + ' sources verified';
    c.mocktest.forEach((m, i) => {
      const d = document.createElement('details'); d.className = 'mq';
      d.innerHTML = '<div class="qn mono">Q' + (i+1) + '</div><div class="qtext">' + m.q + '</div>' +
        '<summary></summary><div class="ans">' + m.a + '<div class="qa-sources" style="margin-top:.5rem;padding-top:.4rem"><span class="cite">' + m.src + '</span></div></div>';
      box.appendChild(d);
    });
  }

  if (state.artifact === 'cards') {
    const box = document.getElementById('art-cards');
    box.innerHTML = '';
    document.getElementById('art-ground').textContent = c.cards.length + ' / ' + c.cards.length + ' sources verified';
    c.cards.forEach((card, i) => {
      const wrap = el('label', 'flip');
      wrap.innerHTML = '<input type="checkbox" id="card-' + state.course + '-' + i + '">' +
        '<div class="flip-inner">' +
        '<div class="flip-face"><div class="k">Front</div><div class="body">' + card.front + '</div><div class="flip-hint">tap to flip</div></div>' +
        '<div class="flip-face flip-back"><div class="k">Back</div><div class="body">' + card.back + '</div></div>' +
        '</div>';
      box.appendChild(wrap);
    });
  }

  if (state.artifact === 'slides') {
    const box = document.getElementById('art-slides');
    box.innerHTML = '';
    document.getElementById('art-ground').textContent = c.slides.length + ' slides';
    c.slides.forEach(s => {
      const d = el('div', 'slide');
      d.innerHTML = '<div class="sn mono">SLIDE ' + s.n + '</div><h4>' + s.title + '</h4><ul>' + s.bullets.map(b => '<li>' + b + '</li>').join('') + '</ul>';
      box.appendChild(d);
    });
  }

  if (state.artifact === 'mindmap') {
    const box = document.getElementById('art-mindmap');
    document.getElementById('art-ground').textContent = 'derived from ' + c.sessions.length + ' sessions';
    const mm = c.mindmap;
    const cx = 130, cy = 160;
    const angleStep = (2 * Math.PI) / mm.nodes.length;
    const r = 150;
    let nodes = '<g class="mm-node center"><rect x="' + (cx-70) + '" y="' + (cy-22) + '" width="140" height="44" rx="10"></rect><text x="' + cx + '" y="' + (cy+5) + '" text-anchor="middle" font-size="13" font-weight="600">' + mm.center + '</text></g>';
    let links = '';
    mm.nodes.forEach((n, i) => {
      const ang = -Math.PI/2 + i * angleStep + (mm.nodes.length === 4 ? Math.PI/4 : 0);
      const nx = cx + r * 1.55 * Math.cos(ang);
      const ny = cy + r * 0.62 * Math.sin(ang) * 1.7 + 10;
      links += '<line class="mm-link" x1="' + cx + '" y1="' + cy + '" x2="' + nx + '" y2="' + ny + '"></line>';
      nodes += '<g class="mm-node"><rect x="' + (nx-62) + '" y="' + (ny-18) + '" width="124" height="36" rx="9"></rect><text x="' + nx + '" y="' + (ny+5) + '" text-anchor="middle" font-size="12">' + n + '</text></g>';
    });
    box.innerHTML = '<svg viewBox="0 0 500 320" xmlns="http://www.w3.org/2000/svg">' + links + nodes + '</svg>';
  }
}

function renderAssignmentView(){
  const c = DATA[state.course];
  const a = c.assignments.find(x => x.id === state.assignment);

  document.getElementById('assign-title').textContent = a.title;
  document.getElementById('assign-prompt').textContent = a.prompt;
  const pills = document.getElementById('assign-pills');
  pills.innerHTML =
    '<span class="pill pill-ochre">Due ' + a.due + '</span>' +
    '<span class="pill pill-neutral">' + a.weight + '</span>' +
    '<span class="pill pill-neutral">' + a.status + '</span>';

  const btn = document.getElementById('explain-btn');
  const panel = document.getElementById('explain-panel');
  btn.textContent = state.explainOpen ? '✦ Hide explanation' : '✦ Explain this assignment';
  panel.hidden = !state.explainOpen;

  const bd = document.getElementById('explain-breakdown');
  bd.innerHTML = '';
  a.explain.breakdown.forEach(pt => bd.appendChild(el('li', null, pt)));

  const tips = document.getElementById('explain-tips');
  tips.innerHTML = '';
  a.explain.tips.forEach(t => {
    const row = el('div', 'explain-tip');
    row.innerHTML = '<span class="cite">' + t.src + '</span><span>' + t.text + '</span>';
    tips.appendChild(row);
  });

  btn.onclick = () => { state.explainOpen = !state.explainOpen; renderAssignmentView(); };
}

function renderAll(){
  renderCourseNav();
  renderSessionNav();
  renderTopbar();
  renderQaThread();
  renderNextAssignment();
  renderArtifactRow();
  renderSessionList();

  document.getElementById('view-home').hidden = state.view !== 'home';
  document.getElementById('view-session').hidden = state.view !== 'session';
  document.getElementById('view-artifact').hidden = state.view !== 'artifact';
  document.getElementById('view-assignment').hidden = state.view !== 'assignment';

  if (state.view === 'session') renderSessionView();
  if (state.view === 'artifact') renderArtifactView();
  if (state.view === 'assignment') renderAssignmentView();
}

document.querySelectorAll('[data-back]').forEach(b => b.onclick = () => { state.view = 'home'; renderAll(); });

document.getElementById('socratic-toggle').onclick = (e) => {
  const pressed = e.currentTarget.getAttribute('aria-pressed') === 'true';
  e.currentTarget.setAttribute('aria-pressed', String(!pressed));
};

document.getElementById('ask-send').onclick = () => {
  const input = document.getElementById('ask-input');
  if (input.value.trim()) input.value = '';
  document.getElementById('qa-thread').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
};
document.getElementById('ask-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') document.getElementById('ask-send').click();
});

/* ---------- onboarding ---------- */
const AVAILABLE_COURSES = [
  { code: "49797", name: "Advanced AI for Industry and Society", checked: true },
  { code: "18654", name: "Software Testing and Operations", checked: true },
  { code: "15513", name: "Cost Models for Modern Architectures", checked: false },
  { code: "05899", name: "Special Topics: Behavioral Economics", checked: false },
  { code: "90717", name: "Financial Statement Analysis", checked: false }
];

function goStage(name){
  ['keys', 'courses', 'indexing', 'app'].forEach(s => {
    document.getElementById('stage-' + s).hidden = s !== name;
  });
  if (name === 'courses') renderCoursePick();
  if (name === 'indexing') runIndexing();
}

function renderCoursePick(){
  const wrap = document.getElementById('course-pick');
  wrap.innerHTML = '';
  AVAILABLE_COURSES.forEach((c, i) => {
    const row = el('label', 'course-row');
    row.innerHTML = '<input type="checkbox" data-idx="' + i + '"' + (c.checked ? ' checked' : '') + '>' +
      '<span class="cmeta"><div class="ccode">' + c.code + '</div><div class="cname">' + c.name + '</div></span>';
    wrap.appendChild(row);
  });
  wrap.querySelectorAll('input[type="checkbox"]').forEach(inp => {
    inp.addEventListener('change', e => {
      AVAILABLE_COURSES[+e.target.dataset.idx].checked = e.target.checked;
      updateCourseCount();
    });
  });
  updateCourseCount();
}

function updateCourseCount(){
  const n = AVAILABLE_COURSES.filter(c => c.checked).length;
  document.getElementById('course-count').textContent = n + ' selected';
  document.getElementById('btn-courses').disabled = n === 0;
}

function runIndexing(){
  const wrap = document.getElementById('index-list');
  wrap.innerHTML = '';
  const btn = document.getElementById('btn-indexing');
  btn.disabled = true;
  const rows = [];
  Object.keys(DATA).forEach(code => {
    const box = el('div', 'index-course', '<div class="icname">' + DATA[code].code + '</div>');
    ['Assignments', 'Modules', 'Slides & files'].forEach(label => {
      const row = el('div', 'index-row', '<span class="stat"></span><span>' + label + '</span>');
      box.appendChild(row);
      rows.push(row);
    });
    wrap.appendChild(box);
  });
  rows.forEach((row, i) => {
    setTimeout(() => row.classList.add('busy'), i * 260);
    setTimeout(() => {
      row.classList.remove('busy');
      row.classList.add('done');
      row.querySelector('.stat').textContent = '✓';
    }, i * 260 + 380);
  });
  setTimeout(() => { btn.disabled = false; }, rows.length * 260 + 500);
}

function updateKeysBtn(){
  const ok = document.getElementById('key-canvas').value.trim() && document.getElementById('key-openai').value.trim();
  document.getElementById('btn-keys').disabled = !ok;
}
document.getElementById('key-canvas').addEventListener('input', updateKeysBtn);
document.getElementById('key-openai').addEventListener('input', updateKeysBtn);
updateKeysBtn();

document.getElementById('btn-keys').onclick = () => goStage('courses');
document.getElementById('btn-courses').onclick = () => goStage('indexing');
document.getElementById('btn-indexing').onclick = () => goStage('app');
document.querySelectorAll('[data-stage-back]').forEach(b => b.onclick = () => goStage(b.dataset.stageBack));

renderAll();

/* ---------- Step 1 sidecar PoC — temporary debug badge, not real UI ---------- */
(function pingSidecar() {
  const badge = document.createElement('div');
  badge.id = 'sidecar-debug-badge';
  badge.style.cssText = 'position:fixed;bottom:8px;right:8px;z-index:9999;' +
    'font-family:monospace;font-size:11px;padding:4px 8px;border-radius:6px;' +
    'background:#333;color:#fff;opacity:0.85;';
  badge.textContent = 'sidecar: checking…';
  document.body.appendChild(badge);

  const MAX_ATTEMPTS = 10;
  const RETRY_DELAY_MS = 400;

  // Uses the Tauri HTTP plugin's fetch (routed through the Rust backend via
  // IPC), not the webview's own fetch: WKWebView blocks a plain fetch() to
  // http://127.0.0.1 from this app's custom-scheme origin regardless of
  // CORS headers, since the request never reaches the webview's network
  // stack at all with this plugin.
  //
  // Retries with backoff: the sidecar is a PyInstaller onefile binary,
  // which self-extracts to a temp dir on every launch before it can bind
  // the port, so the very first ping (fired as soon as this script runs)
  // can race ahead of the backend actually listening. Real API calls will
  // need the same tolerance once they replace this debug badge.
  function attempt(n) {
    window.__TAURI__.http.fetch('http://127.0.0.1:8756/ping')
      .then(r => r.json())
      .then(data => {
        badge.textContent = 'sidecar: ' + JSON.stringify(data) + (n > 1 ? ' (attempt ' + n + ')' : '');
        badge.style.background = '#2d6a4f';
      })
      .catch(err => {
        if (n < MAX_ATTEMPTS) {
          badge.textContent = 'sidecar: retrying… (' + n + '/' + MAX_ATTEMPTS + ')';
          setTimeout(() => attempt(n + 1), RETRY_DELAY_MS);
          return;
        }
        let detail;
        try { detail = JSON.stringify(err); } catch (_) { detail = String(err); }
        if (!detail || detail === '{}') detail = String(err);
        badge.textContent = 'sidecar: unreachable (' + detail + ')';
        badge.style.background = '#9d2f2f';
        console.error('sidecar ping failed after retries', err);
      });
  }

  attempt(1);
})();
