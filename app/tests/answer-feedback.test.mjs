import assert from 'node:assert/strict';
import { after, afterEach, test } from 'node:test';
import { JSDOM } from 'jsdom';
import { createServer } from 'vite';
import React, { act } from 'react';

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.requestAnimationFrame = (fn) => { fn(); return 0; };
const { createRoot } = await import('react-dom/client');
const vite = await createServer({
  configFile: false,
  server: { middlewareMode: true, hmr: false, ws: false },
  appType: 'custom',
  plugins: [{
    name: 'feedback-test-sidecar',
    enforce: 'pre',
    resolveId(id) { if (id === '../../sidecar') return '\0feedback-test-sidecar'; },
    load(id) {
      if (id === '\0feedback-test-sidecar') return ['getConversation', 'askQuestion', 'saveAnswerFeedback']
        .map(name => `export const ${name} = (...args) => globalThis.feedbackTestSidecar.${name}(...args);`).join('\n');
    },
  }],
});
after(async () => { await vite.close(); dom.window.close(); });
const { default: AnswerFeedback } = await vite.ssrLoadModule('/src/components/app/AnswerFeedback.tsx');
const { default: ChatPanel } = await vite.ssrLoadModule('/src/components/app/ChatPanel.tsx');
let root;
afterEach(async () => { if (root) await act(async () => root.unmount()); document.body.replaceChildren(); });

const feedback = (rating, note = '') => ({ rating, note, updated_at: '2026-11-10T12:00:00Z' });
async function mount(initialFeedback, onSave) {
  const container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(React.createElement(AnswerFeedback, { initialFeedback, onSave })));
}
const button = (name) => [...document.querySelectorAll('button')].find(b => b.textContent.trim() === name);
const click = async (name) => { assert.ok(button(name), `missing ${name} button`); await act(async () => button(name).click()); };

test('saves a rating, switches it, and clicking it again clears it', async () => {
  const calls = [];
  await mount(null, async (rating, note) => { calls.push([rating, note]); return rating ? feedback(rating, note) : null; });
  assert.equal(button('Helpful').getAttribute('aria-pressed'), 'false');
  await click('Helpful');
  assert.equal(button('Helpful').getAttribute('aria-pressed'), 'true');
  await click('Not helpful');
  assert.equal(button('Helpful').getAttribute('aria-pressed'), 'false');
  assert.equal(button('Not helpful').getAttribute('aria-pressed'), 'true');
  await click('Not helpful');
  assert.equal(button('Not helpful').getAttribute('aria-pressed'), 'false');
  assert.deepEqual(calls, [['up', ''], ['down', ''], [null, '']]);
});

test('restores saved feedback and saves an edited optional note', async () => {
  const calls = [];
  await mount(feedback('down', 'Missing a source'), async (rating, note) => { calls.push([rating, note]); return feedback(rating, note); });
  assert.equal(button('Not helpful').getAttribute('aria-pressed'), 'true');
  await click('Edit note');
  const field = document.querySelector('textarea');
  assert.equal(field.value, 'Missing a source');
  assert.equal(field.maxLength, 500);
  await act(async () => {
    Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype, 'value').set.call(field, 'Wrong deadline');
    field.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  });
  await click('Save note');
  assert.deepEqual(calls, [['down', 'Wrong deadline']]);
  assert.ok(document.body.textContent.includes('Wrong deadline'));
});

test('a failed write retains the saved vote and lets the user retry', async () => {
  let fails = true;
  await mount(feedback('up'), async (rating, note) => {
    if (fails) throw new Error('Could not save feedback');
    return feedback(rating, note);
  });
  await click('Not helpful');
  assert.equal(button('Helpful').getAttribute('aria-pressed'), 'true');
  assert.match(document.querySelector('[role="alert"]').textContent, /Could not save/);
  fails = false;
  await click('Not helpful');
  assert.equal(button('Not helpful').getAttribute('aria-pressed'), 'true');
  assert.equal(document.querySelector('[role="alert"]'), null);
});

test('a pending save disables controls and prevents duplicate writes', async () => {
  let resolve;
  let calls = 0;
  await mount(null, () => { calls++; return new Promise(r => { resolve = r; }); });
  await click('Helpful');
  assert.equal(button('Helpful').disabled, true);
  assert.equal(button('Not helpful').disabled, true);
  await click('Not helpful');
  assert.equal(calls, 1);
  await act(async () => resolve(feedback('up')));
  assert.equal(button('Helpful').disabled, false);
});

test('chat feedback uses the saved index after errors and never appears while streaming or unsaved', async () => {
  const saved = { question: 'First question', answer: 'First answer', citations: [], grounded: false, feedback: feedback('up', 'Clear explanation') };
  const calls = [];
  let finish;
  globalThis.feedbackTestSidecar = {
    getConversation: async () => ({ title: 'Chat', turns: [saved] }),
    saveAnswerFeedback: async (...args) => { calls.push(args); return feedback(args[3], args[4]); },
    askQuestion: async (_course, _name, question, _history, cid, onEvent) => {
      onEvent({ conversation_id: cid });
      if (question === 'fail') {
        onEvent({ error: 'Interrupted' });
        onEvent({ done: true });
        return;
      }
      onEvent({ delta: 'An answer' });
      return new Promise(resolve => { finish = (index) => { onEvent({ done: true, turn_index: index }); resolve(); }; });
    },
  };
  const container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(React.createElement(ChatPanel, {
    courseId: 55710, courseName: 'Testing', conversationId: 'c-chat', suggestions: [],
    onConversationSaved() {}, onOpenCitation() {},
  })));
  assert.ok(button('Helpful'), document.body.innerHTML);
  assert.equal(button('Helpful').getAttribute('aria-pressed'), 'true');
  assert.ok(document.body.textContent.includes('Clear explanation'));
  const controls = () => document.querySelectorAll('[aria-label="Answer feedback"]');
  async function send(question) {
    await act(async () => {
      const field = document.querySelector('.composer textarea');
      Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype, 'value').set.call(field, question);
      field.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    });
    await click('Ask');
  }
  await send('fail');
  assert.equal(controls().length, 1);
  await send('next');
  assert.equal(controls().length, 1);
  // Other concurrent requests can append turns too; UI positions aren't IDs.
  await act(async () => finish(4));
  assert.equal(controls().length, 2);
  await act(async () => [...controls()[1].querySelectorAll('button')].find(b => b.textContent === 'Not helpful').click());
  assert.deepEqual(calls, [[55710, 'c-chat', 4, 'down', '']]);
  await send('deleted during stream');
  await act(async () => finish(undefined));
  assert.equal(controls().length, 2);
});
