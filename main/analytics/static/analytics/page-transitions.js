(() => {
  'use strict';

  const DURATION_MS = 450;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const body = document.body;

  // The reusable fade entrance: opacity 0 -> 1. This is the
  // "PageFadeTransition"/"applyFadeTransition()" component: any other
  // trigger on the site can call window.applyFadeTransition() directly.
  function applyFadeTransition() {
    if (reduceMotion.matches) return;
    body.style.opacity = '0';
    void body.offsetWidth;
    body.classList.add('is-fade-entering');

    requestAnimationFrame(() => {
      requestAnimationFrame(() => { body.style.opacity = '1'; });
    });

    let settled = false;
    function cleanup() {
      if (settled) return;
      settled = true;
      body.removeEventListener('transitionend', onEnd);
      body.classList.remove('is-fade-entering');
      body.style.opacity = '';
    }
    function onEnd(event) {
      if (event.target !== body || event.propertyName !== 'opacity') return;
      cleanup();
    }
    body.addEventListener('transitionend', onEnd);
    window.setTimeout(cleanup, DURATION_MS + 300);
  }

  window.PageFadeTransition = { enter: applyFadeTransition };
  window.applyFadeTransition = applyFadeTransition;

  // Run the entrance for THIS page load, continuing from the pre-paint
  // starting state the inline snippet at the top of <body> already set (so
  // there's no flash of the page sitting fully opaque first).
  if (!reduceMotion.matches) applyFadeTransition();

  function isSameOrigin(href) {
    try { return new URL(href, window.location.href).origin === window.location.origin; }
    catch (error) { return false; }
  }

  // Outgoing: fade THIS page out before the browser actually navigates, so
  // the crossfade reads as one continuous motion rather than a cut. The
  // next page then fades in over it with the entrance above.
  document.addEventListener('click', (event) => {
    if (reduceMotion.matches) return;
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

    const link = event.target.closest('a[href]');
    if (!link) return;
    if (link.target && link.target !== '_self') return;
    if (link.hasAttribute('download')) return;
    if (link.dataset.noTransition !== undefined) return;

    const rawHref = link.getAttribute('href');
    if (!rawHref || rawHref.startsWith('#') || rawHref.startsWith('mailto:') || rawHref.startsWith('tel:')) return;
    if (!isSameOrigin(link.href)) return;

    const targetUrl = new URL(link.href, window.location.href);
    const current = window.location;
    // 같은 페이지 안의 앵커 이동(#섹션)은 그대로 브라우저 기본 동작에 맡긴다.
    if (targetUrl.pathname === current.pathname && targetUrl.search === current.search && targetUrl.hash) return;

    event.preventDefault();
    body.classList.add('is-fade-leaving');
    window.setTimeout(() => window.location.assign(link.href), DURATION_MS);
  });

  // A page reached via Back/Forward can be served from bfcache mid-fade
  // (still transparent) — reset it so it shows normally.
  window.addEventListener('pageshow', (event) => {
    if (!event.persisted) return;
    body.classList.remove('is-fade-entering', 'is-fade-leaving');
    body.style.transition = 'none';
    body.style.opacity = '';
    void body.offsetWidth;
    body.style.transition = '';
  });
})();
