(function (root) {
  function openProtocolUri(uri, documentRef = document) {
    const link = documentRef.createElement('a');
    link.href = uri;
    link.hidden = true;
    documentRef.body.appendChild(link);
    link.click();
    link.remove();
  }
  function beginCodexHandoff({ uri, openUri, onWaiting, onUnconfirmed, setTimer = setTimeout, clearTimer = clearTimeout, delay = 12000 }) {
    let cancelled = false;
    onWaiting();
    const timer = setTimer(() => {
      if (!cancelled) onUnconfirmed();
    }, delay);
    openUri(uri);
    return () => { cancelled = true; clearTimer(timer); };
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { beginCodexHandoff, openProtocolUri };
  root.StudioFlowCodexHandoff = { beginCodexHandoff, openProtocolUri };
})(globalThis);
