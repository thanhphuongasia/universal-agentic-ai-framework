/**
 * ryuu-eval-frontend — vanilla bundle (Preact + htm via CDN).
 *
 * Loads via index.html which sets window.__ryuu_preact and window.RYUU_EVAL_CONFIG.
 * No build step required — runs directly trong browser.
 *
 * 5 components composed in EvalApp root:
 *   - TemplateGallery
 *   - CaseEditor      (split input/expected JSON editors)
 *   - ProgressLog     (live SSE event stream)
 *   - DiffView        (actual vs expected)
 *   - RefineHistoryPanel
 *   - OptimizeButton  (+ result modal)
 */

import { html, render } from 'https://esm.sh/htm@3.1.1/preact';
import { useEffect, useState, useRef, useCallback } from 'https://esm.sh/preact@10.22.0/hooks';

// Auto-detect apiPrefix from this script's URL: /api/<whatever>/ui/ryuu-eval.js
// → apiPrefix = /api/<whatever>. Works regardless of mount point (eval, eval2, etc.).
// Override via window.RYUU_EVAL_CONFIG.apiPrefix if needed.
function _autoDetectApiPrefix() {
  try {
    const url = new URL(import.meta.url);
    const m = url.pathname.match(/^(.*)\/ui\/ryuu-eval\.js$/);
    if (m) return m[1];
  } catch (_) { /* fall through */ }
  return "/api/eval";
}
const CFG = Object.assign({ apiPrefix: _autoDetectApiPrefix() }, window.RYUU_EVAL_CONFIG || {});
const API = (path) => `${CFG.apiPrefix}${path}`;

// ============================================================================
// API client
// ============================================================================

async function api(path, init = {}) {
  const res = await fetch(API(path), {
    headers: { "Content-Type": "application/json", ...(init.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${path}: ${res.status} ${text.slice(0, 200)}`);
  }
  return res.json();
}

// ============================================================================
// TemplateGallery — pick a template để start a new case
// ============================================================================

function TemplateGallery({ templates, selectedId, onSelect }) {
  if (!templates.length) {
    return html`<div class="empty-state">No templates registered</div>`;
  }
  return html`
    <ul class="template-list">
      ${templates.map(t => html`
        <li
          class="template-item ${t.template_id === selectedId ? 'selected' : ''}"
          onClick=${() => onSelect(t)}
        >
          <strong>${t.title || t.template_id}</strong>
          <small>${t.description || ''}</small>
          <div>
            ${(t.tags || []).map(tag => html`<span class="tag">${tag}</span>`)}
          </div>
        </li>
      `)}
    </ul>
  `;
}

// ============================================================================
// CaseList — pick existing case từ suite
// ============================================================================

function CaseList({ cases, selectedId, onSelect, refineMeta }) {
  if (!cases.length) {
    return html`<div class="empty-state">No cases yet. Add from template ↑</div>`;
  }
  return html`
    <ul class="case-list">
      ${cases.map(c => {
        const meta = refineMeta[c.case_id] || {};
        const statusClass = meta.passed === true ? 'passed'
                           : meta.passed === false ? 'failed' : '';
        const refineBadge = meta.refine_count > 0
          ? html`<span class="case-status refined">refined×${meta.refine_count}</span>`
          : null;
        return html`
          <li
            class="case-item ${c.case_id === selectedId ? 'selected' : ''}"
            onClick=${() => onSelect(c)}
          >
            <strong>${c.case_id}</strong>
            <span class="case-status ${statusClass}">
              ${meta.passed === true ? '✅' : meta.passed === false ? '❌' : ''}
            </span>
            ${refineBadge}
          </li>
        `;
      })}
    </ul>
  `;
}

// ============================================================================
// CaseEditor — split editor for input + expected
// ============================================================================

function CaseEditor({ caseData, onChange }) {
  const inputJson = JSON.stringify(caseData.input ?? {}, null, 2);
  const expectedJson = JSON.stringify(caseData.expected ?? {}, null, 2);

  const handle = (field) => (e) => {
    try {
      const parsed = JSON.parse(e.target.value);
      onChange({ ...caseData, [field]: parsed });
    } catch (err) {
      // Ignore parse errors during typing — only commit when valid
    }
  };

  return html`
    <div class="editor-grid">
      <div class="editor-pane">
        <h4>INPUT (JSON)</h4>
        <textarea
          value=${inputJson}
          onInput=${handle('input')}
          spellcheck="false"
        ></textarea>
      </div>
      <div class="editor-pane">
        <h4>EXPECTED (JSON)</h4>
        <textarea
          value=${expectedJson}
          onInput=${handle('expected')}
          spellcheck="false"
        ></textarea>
      </div>
    </div>
  `;
}

// ============================================================================
// SmartCaseEditor — schema-driven form when template has input_schema.properties
// ============================================================================

function SmartCaseEditor({ caseData, template, onChange }) {
  const props = template?.input_schema?.properties || {};
  const required = template?.input_schema?.required || [];
  const hasSchema = Object.keys(props).length > 0;

  if (!hasSchema) {
    return html`<${CaseEditor} caseData=${caseData} onChange=${onChange} />`;
  }

  const input = caseData.input || {};
  const expectedJson = JSON.stringify(caseData.expected ?? {}, null, 2);
  const setField = (key, value) => onChange({ ...caseData, input: { ...input, [key]: value } });

  const renderField = (key, p) => {
    const label = p.title || key;
    const req = required.includes(key);
    const val = input[key];

    if (p.enum) return html`
      <div class="field-row" key=${key}>
        <label>${label}${req ? ' *' : ''}</label>
        <select value=${val ?? ''} onChange=${e => setField(key, e.target.value)}>
          <option value="">— select —</option>
          ${p.enum.map(v => html`<option value=${v}>${v}</option>`)}
        </select>
      </div>`;

    if (p.type === 'boolean') return html`
      <div class="field-row" key=${key}>
        <label>${label}</label>
        <input type="checkbox" checked=${!!val} onChange=${e => setField(key, e.target.checked)} />
      </div>`;

    if (p.type === 'integer' || p.type === 'number') return html`
      <div class="field-row" key=${key}>
        <label>${label}${req ? ' *' : ''}</label>
        <input type="number" value=${val ?? ''}
               onInput=${e => setField(key, Number(e.target.value))} />
      </div>`;

    if (p.type === 'array' || p.type === 'object') {
      const jsonVal = JSON.stringify(val ?? (p.type === 'array' ? [] : {}), null, 2);
      return html`
        <div class="field-row" key=${key}>
          <label>${label}${req ? ' *' : ''}</label>
          <textarea rows="3" value=${jsonVal} spellcheck="false"
                    onInput=${e => { try { setField(key, JSON.parse(e.target.value)); } catch {} }}>
          </textarea>
        </div>`;
    }

    return html`
      <div class="field-row" key=${key}>
        <label>${label}${req ? ' *' : ''}</label>
        <input type="text" value=${val ?? ''} onInput=${e => setField(key, e.target.value)} />
      </div>`;
  };

  return html`
    <div class="editor-grid">
      <div class="editor-pane">
        <h4>INPUT <span class="schema-badge">form</span></h4>
        <div class="schema-form">
          ${Object.entries(props).map(([k, p]) => renderField(k, p))}
        </div>
      </div>
      <div class="editor-pane">
        <h4>EXPECTED (JSON)</h4>
        <textarea value=${expectedJson} spellcheck="false"
          onInput=${e => { try { onChange({ ...caseData, expected: JSON.parse(e.target.value) }); } catch {} }}>
        </textarea>
      </div>
    </div>`;
}

// ============================================================================
// FixtureList — read-only fixture cases from fixtures_dir
// ============================================================================

function FixtureList({ fixtures, onClone }) {
  if (!fixtures.length) return null;
  return html`
    <ul class="case-list">
      ${fixtures.map(f => html`
        <li class="case-item" key=${f.case_id}>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:0.25rem;">
            <strong style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
              ${f.case_id}
            </strong>
            <span class="fixture-badge">📌</span>
          </div>
          <small>${f._file || 'fixture'}</small>
          <button class="clone-btn" onClick=${() => onClone(f)}>Clone to editor</button>
        </li>
      `)}
    </ul>`;
}

// ============================================================================
// ProgressLog — live SSE event log
// ============================================================================

function ProgressLog({ events }) {
  const ref = useRef();

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [events.length]);

  if (!events.length) {
    return null;
  }
  return html`
    <div class="progress-log" ref=${ref}>
      ${events.map((ev, i) => html`
        <div class="progress-event ${ev.type === 'error' ? 'error' :
                                       ev.type.startsWith('refine') ? 'refine' : ''}">
          <span class="type">[${ev.type}]</span>
          ${ev.case_id ? html` <span class="case-id">${ev.case_id}</span>` : null}
          ${' '}${JSON.stringify(ev.payload || {}).slice(0, 200)}
        </div>
      `)}
    </div>
  `;
}

// ============================================================================
// DiffView — actual vs expected JSON diff (line-based heuristic)
// ============================================================================

function DiffView({ actual, expected }) {
  if (actual === null || actual === undefined) return null;

  const actualLines = JSON.stringify(actual, null, 2).split('\n');
  const expectedLines = JSON.stringify(expected ?? {}, null, 2).split('\n');

  // Simple line-by-line diff (good enough for JSON output)
  const maxLen = Math.max(actualLines.length, expectedLines.length);
  const rows = [];
  for (let i = 0; i < maxLen; i++) {
    const e = expectedLines[i] ?? '';
    const a = actualLines[i] ?? '';
    if (e === a) {
      rows.push({ type: 'same', text: e });
    } else {
      if (e) rows.push({ type: 'expected', text: e });
      if (a) rows.push({ type: 'actual', text: a });
    }
  }

  return html`
    <div class="diff-view">
      <h4 style="margin: 0 0 0.5rem 0;">Diff (expected ✓ / actual ✗)</h4>
      ${rows.map(r => html`
        <div class="diff-line ${r.type}">
          <span class="diff-marker">${
            r.type === 'expected' ? '✓' :
            r.type === 'actual' ? '✗' : ' '
          }</span>
          ${r.text}
        </div>
      `)}
    </div>
  `;
}

// ============================================================================
// RefineHistoryPanel — show LLM mistakes + feedback iterations
// ============================================================================

function RefineHistoryPanel({ suiteId, caseId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!suiteId) return;
    setLoading(true);
    try {
      const result = await api(`/refine_history/${suiteId}?limit=50`);
      setData(result);
    } catch (err) {
      console.warn("refine_history fetch failed:", err);
      setData({ events: [] });
    } finally {
      setLoading(false);
    }
  }, [suiteId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return html`<div class="empty-state">Loading refine history…</div>`;
  if (!data || !data.events || !data.events.length) return null;

  const stats = data.stats || {};

  return html`
    <div class="refine-panel">
      <h4>Refine History (${data.events.length} events
        ${stats.avg_refines ? html`, avg ${stats.avg_refines.toFixed(1)} refines` : null})</h4>
      ${data.events.slice(-3).map(ev => html`
        <div>
          <strong>Refine count: ${ev.refine_count} ${ev.passed ? '✅' : '❌'}</strong>
          ${(ev.feedback_history || []).map((fb, i) => html`
            <div class="refine-iter">
              <strong>Iter ${i+1}:</strong> ${fb.slice(0, 300)}
            </div>
          `)}
        </div>
      `)}
    </div>
  `;
}

// ============================================================================
// OptimizeButton — fire PromptOptimizer + show result modal
// ============================================================================

function OptimizeButton({ suiteId }) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const optimize = async () => {
    setRunning(true);
    setError(null);
    try {
      const res = await api(`/optimize/${suiteId}`, {
        method: 'POST',
        body: JSON.stringify({ max_rounds: 2, threshold_pp: 5.0 }),
      });
      setResult(res);
    } catch (err) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  };

  return html`
    <span>
      <button onClick=${optimize} disabled=${running}>
        ${running ? 'Optimizing… (~30s)' : '▶ Optimize prompt'}
      </button>
      ${error && html`<div class="error-banner">${error}</div>`}
      ${result && html`
        <div class="modal-backdrop" onClick=${() => setResult(null)}>
          <div class="modal" onClick=${e => e.stopPropagation()}>
            <h2>Optimization Result</h2>
            <p><strong>Status:</strong> ${result.status}</p>
            ${result.reason && html`<p><em>${result.reason}</em></p>`}
            ${result.baseline_summary && html`<p><strong>${result.baseline_summary}</strong></p>`}
            ${result.best_summary && html`<p><strong>${result.best_summary}</strong></p>`}
            ${result.improvement_summary && html`<p>${result.improvement_summary}</p>`}
            ${result.applied && html`
              <p>✅ New YAML written to <code>${result.output_yaml}</code></p>
              <p>Diff: ${result.diff_chars > 0 ? '+' : ''}${result.diff_chars} chars</p>
            `}
            ${result.stdout_tail && html`
              <details>
                <summary>stdout tail</summary>
                <pre>${result.stdout_tail}</pre>
              </details>
            `}
            <button onClick=${() => setResult(null)}>Close</button>
          </div>
        </div>
      `}
    </span>
  `;
}

// ============================================================================
// EvalApp — root composition
// ============================================================================

function EvalApp() {
  const [suiteId, setSuiteId] = useState(CFG.defaultSuiteId || null);
  const [suites, setSuites] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [cases, setCases] = useState([]);
  const [fixtures, setFixtures] = useState([]);
  const [selectedCaseId, setSelectedCaseId] = useState(null);
  const [caseData, setCaseData] = useState({ input: {}, expected: {} });
  const [events, setEvents] = useState([]);
  const [runResult, setRunResult] = useState(null);
  const [refineMeta, setRefineMeta] = useState({});
  const [error, setError] = useState(null);
  const [runningCase, setRunningCase] = useState(false);
  const sseRef = useRef(null);

  // Load templates + extract suites
  useEffect(() => {
    api('/templates').then(tpls => {
      setTemplates(tpls);
      const uniqueSuites = [...new Set(tpls.map(t => t.suite_id))];
      setSuites(uniqueSuites);
      if (!suiteId && uniqueSuites.length) setSuiteId(uniqueSuites[0]);
    }).catch(e => setError(`Templates: ${e.message}`));
  }, []);

  // Load cases when suite changes
  useEffect(() => {
    if (!suiteId) { setCases([]); return; }
    api(`/suites/${suiteId}/cases`).then(setCases)
      .catch(e => setError(`Cases: ${e.message}`));
  }, [suiteId]);

  // Load read-only fixture cases when suite changes
  useEffect(() => {
    if (!suiteId) { setFixtures([]); return; }
    api(`/fixtures/${suiteId}`).then(setFixtures).catch(() => setFixtures([]));
  }, [suiteId]);

  // Pick template → seed new case from first example
  const onPickTemplate = (tpl) => {
    const example = (tpl.examples || [])[0] || { input: {}, expected: {} };
    setCaseData({
      case_id: `new_${Date.now()}`,
      input: example.input,
      expected: example.expected,
      _template_id: tpl.template_id,
    });
    setSelectedCaseId(null);
    setRunResult(null);
    setEvents([]);
  };

  // Pick existing case → load into editor
  const onPickCase = (c) => {
    setCaseData({ case_id: c.case_id, input: c.input, expected: c.expected });
    setSelectedCaseId(c.case_id);
    setRunResult(null);
    setEvents([]);
  };

  // Save case (POST template's create endpoint)
  const onSave = async () => {
    if (!caseData._template_id) {
      setError("Select a template first");
      return;
    }
    try {
      await api(`/templates/${caseData._template_id}/cases`, {
        method: 'POST',
        body: JSON.stringify({
          case_id: caseData.case_id,
          input: caseData.input,
          expected: caseData.expected,
        }),
      });
      // Reload cases
      const updated = await api(`/suites/${suiteId}/cases`);
      setCases(updated);
      setError(null);
    } catch (err) {
      setError(`Save: ${err.message}`);
    }
  };

  // Clone fixture into editor as new (unsaved) case
  const onCloneFixture = (fixture) => {
    setCaseData({
      case_id: `clone_${fixture.case_id}`,
      input: fixture.input,
      expected: fixture.expected,
    });
    setSelectedCaseId(null);
    setRunResult(null);
    setEvents([]);
  };

  // Run single case from editor (blocking, not SSE)
  const onRunSingle = async () => {
    if (!caseData.case_id && !caseData._template_id) return;
    setRunningCase(true);
    setRunResult(null);
    setError(null);
    try {
      const result = await api('/run/single', {
        method: 'POST',
        body: JSON.stringify({
          suite_id: suiteId,
          case_id: caseData.case_id || `adhoc_${Date.now()}`,
          input: caseData.input,
          expected: caseData.expected,
        }),
      });
      setRunResult(result);
    } catch (err) {
      setError(`Run case: ${err.message}`);
    } finally {
      setRunningCase(false);
    }
  };

  // Run suite (streaming SSE)
  const onRun = () => {
    if (!suiteId) return;
    setEvents([]);
    setRunResult(null);
    setError(null);

    if (sseRef.current) sseRef.current.close();
    const sse = new EventSource(API(`/run/stream/${suiteId}`));
    sseRef.current = sse;

    sse.onmessage = (msg) => {
      try {
        const ev = JSON.parse(msg.data);
        setEvents(prev => [...prev, ev]);

        if (ev.type === 'case_done') {
          setRefineMeta(prev => ({
            ...prev,
            [ev.case_id]: { passed: ev.payload.passed },
          }));
          // If selected case → store result
          if (ev.case_id === selectedCaseId) {
            setRunResult(ev.payload);
          }
        }
        if (ev.type === 'refine_done') {
          setRefineMeta(prev => ({
            ...prev,
            [ev.case_id]: {
              ...prev[ev.case_id],
              refine_count: ev.payload.refine_count,
              passed: ev.payload.passed,
            },
          }));
        }
        if (ev.type === 'suite_done') {
          sse.close();
        }
      } catch (e) {
        console.error('SSE parse:', e);
      }
    };

    sse.onerror = () => {
      sse.close();
    };
  };

  // Cleanup
  useEffect(() => () => { if (sseRef.current) sseRef.current.close(); }, []);

  const suiteTemplates = templates.filter(t => t.suite_id === suiteId);
  const selectedTemplate = templates.find(t => t.template_id === caseData._template_id) || null;

  return html`
    <div class="eval-app">
      <aside class="eval-sidebar">
        <h3>Suite</h3>
        <select class="suite-picker" value=${suiteId || ''}
                onChange=${e => setSuiteId(e.target.value)}>
          ${suites.map(s => html`<option value=${s}>${s}</option>`)}
        </select>

        <h3>Templates</h3>
        <${TemplateGallery}
          templates=${suiteTemplates}
          selectedId=${caseData._template_id}
          onSelect=${onPickTemplate}
        />

        <h3>Cases (${cases.length})</h3>
        <${CaseList}
          cases=${cases}
          selectedId=${selectedCaseId}
          onSelect=${onPickCase}
          refineMeta=${refineMeta}
        />

        ${fixtures.length > 0 && html`
          <h3>Fixtures (${fixtures.length})</h3>
          <${FixtureList} fixtures=${fixtures} onClone=${onCloneFixture} />
        `}
      </aside>

      <main class="eval-main">
        ${error && html`<div class="error-banner">${error}</div>`}

        <div class="editor-toolbar">
          <button class="primary" onClick=${onRun}>▶ Run suite</button>
          ${(caseData.case_id || caseData._template_id) && html`
            <button onClick=${onRunSingle} disabled=${runningCase || !suiteId}>
              ${runningCase ? '…running' : '▶ Run this case'}
            </button>
          `}
          ${caseData._template_id && html`
            <button onClick=${onSave}>💾 Save case</button>
          `}
          ${suiteId && html`<${OptimizeButton} suiteId=${suiteId} />`}
        </div>

        ${runResult && html`
          <div class="result-summary ${runResult.passed ? 'passed' : 'failed'}">
            <span><span class="label">Status:</span>
                  <span class="value">${runResult.passed ? '✅ Passed' : '❌ Failed'}</span></span>
            <span><span class="label">Latency:</span>
                  <span class="value">${runResult.latency_ms?.toFixed(0)}ms</span></span>
            <span><span class="label">Cost:</span>
                  <span class="value">$${(runResult.cost_usd || 0).toFixed(4)}</span></span>
            ${runResult.scores?.map(s => html`
              <span><span class="label">${s.scorer_id}:</span>
                    <span class="value">${(s.score * 100).toFixed(0)}%</span></span>
            `)}
          </div>
        `}

        <${ProgressLog} events=${events} />

        ${(caseData.case_id || caseData._template_id) && html`
          <${SmartCaseEditor}
            caseData=${caseData}
            template=${selectedTemplate}
            onChange=${setCaseData}
          />
        `}

        ${runResult && html`
          <${DiffView}
            actual=${tryParseJson(runResult._output || runResult.output || '{}')}
            expected=${caseData.expected}
          />
        `}

        ${suiteId && html`<${RefineHistoryPanel} suiteId=${suiteId} caseId=${selectedCaseId} />`}
      </main>
    </div>
  `;
}

function tryParseJson(s) {
  try { return JSON.parse(s); } catch { return s; }
}

// ============================================================================
// Mount
// ============================================================================

function _showFatal(msg) {
  const root = document.getElementById('ryuu-eval-root');
  if (!root) return;
  root.innerHTML =
    '<pre style="padding:1rem;color:#dc2626;background:#fee2e2;' +
    'white-space:pre-wrap;font-family:ui-monospace,monospace;font-size:12px;">' +
    String(msg).replace(/[&<>]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])) +
    '</pre>';
}

window.addEventListener('error', (e) => {
  _showFatal('[JS error] ' + (e.error?.stack || e.message || e));
});
window.addEventListener('unhandledrejection', (e) => {
  _showFatal('[Promise reject] ' + (e.reason?.stack || e.reason || e));
});

const root = document.getElementById('ryuu-eval-root');
if (!root) {
  console.error('ryuu-eval-root div not found');
} else {
  try {
    root.innerHTML = '';
    render(html`<${EvalApp} />`, root);
  } catch (err) {
    _showFatal('[Mount error] ' + (err?.stack || err));
  }
}
