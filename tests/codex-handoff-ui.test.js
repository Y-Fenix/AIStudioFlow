const test = require('node:test');
const assert = require('node:assert/strict');
const { beginCodexHandoff, openProtocolUri } = require('../web/codex-handoff.js');

test('handoff reports pending first and offers recovery when the bridge gives no browser response', () => {
  const events = [];
  let timer;
  beginCodexHandoff({
    openUri: uri => events.push(['open', uri]),
    onWaiting: () => events.push(['waiting']),
    onUnconfirmed: () => events.push(['unconfirmed']),
    uri: 'studioflow-codex://handoff?ticket=one-time',
    setTimer: callback => { timer = callback; return 1; },
    clearTimer: () => {},
  });

  assert.deepEqual(events, [['waiting'], ['open', 'studioflow-codex://handoff?ticket=one-time']]);
  timer();
  assert.deepEqual(events.at(-1), ['unconfirmed']);
});

test('a cancelled handoff never displays stale recovery UI', () => {
  const events = [];
  let timer;
  const cancel = beginCodexHandoff({
    openUri: () => {}, onWaiting: () => {}, onUnconfirmed: () => events.push('unconfirmed'),
    uri: 'studioflow-codex://handoff?ticket=one-time',
    setTimer: callback => { timer = callback; return 1; }, clearTimer: () => {},
  });
  cancel();
  timer();
  assert.deepEqual(events, []);
});

test('custom protocol handoff opens through a temporary link without navigating the workflow page', () => {
  const calls = [];
  const link = { click: () => calls.push('click'), remove: () => calls.push('remove') };
  const documentRef = { createElement: tag => { calls.push(['create', tag]); return link; }, body: {
    appendChild: node => calls.push(['append', node === link]),
  }};
  openProtocolUri('studioflow-codex://handoff?ticket=one-time', documentRef);
  assert.equal(link.href, 'studioflow-codex://handoff?ticket=one-time');
  assert.equal(link.hidden, true);
  assert.deepEqual(calls, [['create', 'a'], ['append', true], 'click', 'remove']);
});
