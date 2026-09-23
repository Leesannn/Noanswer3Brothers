(() => {
  'use strict';

  const root = document.querySelector('[data-motion-root]');
  if (!root) return;

  const stage = root.querySelector('[data-athlete-stage]');
  const canvas = root.querySelector('[data-trajectory-canvas]');
  const context = canvas && canvas.getContext ? canvas.getContext('2d') : null;

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const compactMotion = window.matchMedia('(max-width: 700px)');
  const precisePointer = window.matchMedia('(hover: hover) and (pointer: fine)');

  const sessionKey = 'editorialLandingIntroPlayed';
  const controller = new AbortController();
  const signal = controller.signal;
  const timeouts = [];
  let pageVisible = !document.hidden;
  let resizeTimer = 0;

  function safeSessionGet() {
    try { return sessionStorage.getItem(sessionKey); } catch (error) { return null; }
  }
  function safeSessionSet() {
    try { sessionStorage.setItem(sessionKey, '1'); } catch (error) { /* storage optional */ }
  }
  function clearTimeline() {
    while (timeouts.length) window.clearTimeout(timeouts.pop());
  }

  /* ---------------------------------------------------------------- */
  /* Intro motion: progressive reveal driven by classes on <body>      */
  /* ---------------------------------------------------------------- */
  function initIntroMotion() {
    const body = document.body;

    function addScene(n) { body.classList.add(`is-intro-scene-${n}`); }

    function settle(state) {
      clearTimeline();
      for (let i = 1; i <= 7; i += 1) addScene(i);
      body.classList.remove('is-intro-scene-loading');
      body.classList.add(`is-intro-${state}`);
      body.classList.remove('is-intro-intro');
      safeSessionSet();
      window.dispatchEvent(new CustomEvent('editorial:settled'));
    }

    function playIntro() {
      clearTimeline();
      for (let i = 1; i <= 7; i += 1) body.classList.remove(`is-intro-scene-${i}`);
      body.classList.remove('is-intro-settled', 'is-intro-skipped', 'is-intro-reduced');
      body.classList.add('is-intro-intro');

      const timing = compactMotion.matches
        ? [[1, 0], [2, 250], [3, 700], [4, 1050], [5, 1450], [6, 1850], [7, 2200]]
        : [[1, 0], [2, 450], [3, 1050], [4, 1550], [5, 2150], [6, 2750], [7, 3300]];

      timing.forEach(([scene, delay]) => {
        timeouts.push(window.setTimeout(() => addScene(scene), delay));
      });
      timeouts.push(window.setTimeout(() => settle('settled'), compactMotion.matches ? 2700 : 4000));
    }

    root.querySelector('[data-intro-skip]')?.addEventListener('click', () => settle('skipped'), { signal });
    root.querySelector('[data-intro-replay]')?.addEventListener('click', playIntro, { signal });

    document.addEventListener('visibilitychange', () => { pageVisible = !document.hidden; }, { signal });
    window.addEventListener('pageshow', (event) => {
      pageVisible = !document.hidden;
      if (event.persisted) {
        settle('settled');
        root.querySelectorAll('.figure-ghost').forEach((ghost) => ghost.remove());
        window.dispatchEvent(new CustomEvent('editorial:canvasReady'));
      }
    }, { signal });

    if (reduceMotion.matches) {
      body.classList.add('is-intro-reduced');
    } else if (safeSessionGet()) {
      settle('settled');
    } else {
      playIntro();
    }
  }

  /* ---------------------------------------------------------------- */
  /* Athlete auto-rotation: 이전 동작이 잔상처럼 흐려지며 사라진다         */
  /* ---------------------------------------------------------------- */
  function initAthleteSwitcher() {
    if (!stage) return;
    const images = Array.from(stage.querySelectorAll('[data-athlete-image]'));
    if (images.length < 2) return;
    const wrap = stage.querySelector('.athlete-figure-wrap');

    let index = Math.max(0, images.findIndex((img) => img.classList.contains('is-active')));
    let swimmingLayerTimer = 0;

    function spawnGhost(sourceImage) {
      if (!wrap) return;
      const ghost = sourceImage.cloneNode(true);
      ghost.removeAttribute('data-athlete-image');
      ghost.className = 'figure-ghost';
      ghost.style.objectPosition = window.getComputedStyle(sourceImage).objectPosition;
      ghost.setAttribute('aria-hidden', 'true');
      wrap.appendChild(ghost);
      // 클래스를 바로 붙이면 브라우저가 시작 상태를 못 보고 전환을 건너뛸 수 있어
      // 한 프레임 쉬었다가 붙인다.
      requestAnimationFrame(() => {
        requestAnimationFrame(() => ghost.classList.add('is-fading'));
      });
      timeouts.push(window.setTimeout(() => ghost.remove(), 800));
    }

    function activate(nextIndex) {
      const targetImage = images[nextIndex];
      if (!targetImage) return;
      index = nextIndex;

      const current = images.find((img) => img.classList.contains('is-active'));
      window.clearTimeout(swimmingLayerTimer);
      if (wrap && targetImage.dataset.athleteImage === 'swimming') {
        wrap.classList.add('is-swimming-front');
      } else if (wrap && current?.dataset.athleteImage === 'swimming') {
        swimmingLayerTimer = window.setTimeout(() => {
          wrap.classList.remove('is-swimming-front');
        }, 800);
        timeouts.push(swimmingLayerTimer);
      } else if (wrap) {
        wrap.classList.remove('is-swimming-front');
      }
      if (current && current !== targetImage && !reduceMotion.matches) {
        spawnGhost(current);
      }
      images.forEach((img) => img.classList.toggle('is-active', img === targetImage));
    }

    if (reduceMotion.matches) return;

    const cycleMs = 4500;
    const autoTimer = window.setInterval(() => {
      if (!pageVisible) return;
      activate((index + 1) % images.length);
    }, cycleMs);

    signal.addEventListener('abort', () => {
      window.clearInterval(autoTimer);
      window.clearTimeout(swimmingLayerTimer);
    }, { once: true });
  }

  /* ---------------------------------------------------------------- */
  /* Canvas trajectories: hand-drawn curves connecting cards & figure  */
  /* ---------------------------------------------------------------- */
  function initCanvasTrajectories() {
    if (!context || !canvas || !stage) return;
    if (compactMotion.matches) return;

    const linkGroups = [
      ['[data-stage-card="sport"]', '[data-stage-card="region"]'],
      ['[data-stage-card="region"]', '[data-stage-card="qual"]'],
      ['[data-stage-card="qual"]', '[data-stage-card="org"]'],
      ['[data-stage-badge]', '[data-stage-card="org"]'],
    ];

    let curves = [];
    let progress = 0;
    let frameId = 0;
    let drawn = false;

    function anchor(selector) {
      const el = stage.querySelector(selector);
      if (!el) return null;
      const stageBox = stage.getBoundingClientRect();
      const box = el.getBoundingClientRect();
      return {
        x: box.left - stageBox.left + box.width / 2,
        y: box.top - stageBox.top + box.height / 2,
      };
    }

    function buildCurves() {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      const box = stage.getBoundingClientRect();
      canvas.width = Math.round(box.width * dpr);
      canvas.height = Math.round(box.height * dpr);
      canvas.style.width = `${box.width}px`;
      canvas.style.height = `${box.height}px`;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);

      curves = linkGroups.map(([fromSel, toSel]) => {
        const from = anchor(fromSel);
        const to = anchor(toSel);
        if (!from || !to) return null;
        const mx = (from.x + to.x) / 2 + (to.y - from.y) * .18;
        const my = (from.y + to.y) / 2 - (to.x - from.x) * .18;
        const points = [];
        const steps = 28;
        for (let i = 0; i <= steps; i += 1) {
          const t = i / steps;
          const x = (1 - t) ** 2 * from.x + 2 * (1 - t) * t * mx + t ** 2 * to.x;
          const y = (1 - t) ** 2 * from.y + 2 * (1 - t) * t * my + t ** 2 * to.y;
          points.push({ x, y });
        }
        return points;
      }).filter(Boolean);
    }

    function draw() {
      const box = stage.getBoundingClientRect();
      context.clearRect(0, 0, box.width, box.height);
      context.strokeStyle = 'rgba(17,17,17,.5)';
      context.lineWidth = 1.3;
      context.lineCap = 'round';

      curves.forEach((points) => {
        const count = Math.max(2, Math.round(points.length * progress));
        context.beginPath();
        points.slice(0, count).forEach((point, index) => {
          if (index === 0) context.moveTo(point.x, point.y);
          else context.lineTo(point.x, point.y);
        });
        context.stroke();

        if (progress >= 1) {
          const dot = points[points.length - 1];
          context.beginPath();
          context.fillStyle = '#2457f5';
          context.arc(dot.x, dot.y, 3, 0, Math.PI * 2);
          context.fill();
        }
      });
    }

    function animateIn() {
      if (drawn) return;
      drawn = true;
      const start = performance.now();
      const duration = reduceMotion.matches ? 1 : 900;

      function step(now) {
        progress = Math.min(1, (now - start) / duration);
        draw();
        if (progress < 1 && pageVisible) frameId = window.requestAnimationFrame(step);
      }
      frameId = window.requestAnimationFrame(step);
    }

    buildCurves();
    if (reduceMotion.matches) {
      progress = 1;
      draw();
    } else {
      window.addEventListener('editorial:canvasReady', animateIn, { signal, once: true });
    }

    window.addEventListener('resize', () => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => { buildCurves(); draw(); }, 150);
    }, { passive: true, signal });

    document.addEventListener('visibilitychange', () => {
      if (document.hidden) window.cancelAnimationFrame(frameId);
    }, { signal });

    signal.addEventListener('abort', () => window.cancelAnimationFrame(frameId), { once: true });

    // Fallback: if intro settles without ever dispatching canvasReady (e.g. repeat visit), draw immediately.
    if (safeSessionGet() || reduceMotion.matches) {
      progress = 1;
      draw();
    } else {
      timeouts.push(window.setTimeout(() => window.dispatchEvent(new CustomEvent('editorial:canvasReady')), compactMotion.matches ? 1850 : 2750));
    }
  }

  /* ---------------------------------------------------------------- */
  /* Pointer parallax (desktop only, subtle)                           */
  /* ---------------------------------------------------------------- */
  function initPointerParallax() {
    if (!stage || !precisePointer.matches || reduceMotion.matches) return;
    const layers = [
      stage.querySelector('.athlete-figure-wrap'),
      ...stage.querySelectorAll('.stage-card'),
      stage.querySelector('.stage-badge'),
    ].filter(Boolean);
    if (!layers.length) return;

    const pointer = { x: 0, y: 0, targetX: 0, targetY: 0 };
    let frameId = 0;

    function onMove(event) {
      const box = stage.getBoundingClientRect();
      pointer.targetX = ((event.clientX - box.left) / box.width - .5) * 16;
      pointer.targetY = ((event.clientY - box.top) / box.height - .5) * 12;
    }

    function render() {
      pointer.x += (pointer.targetX - pointer.x) * .08;
      pointer.y += (pointer.targetY - pointer.y) * .08;
      layers.forEach((layer, index) => {
        const depth = index === 0 ? .3 : .6 + index * .08;
        layer.style.translate = `${(pointer.x * depth).toFixed(2)}px ${(pointer.y * depth).toFixed(2)}px`;
      });
      frameId = window.requestAnimationFrame(render);
    }

    stage.addEventListener('pointermove', onMove, { passive: true, signal });
    stage.addEventListener('pointerleave', () => { pointer.targetX = 0; pointer.targetY = 0; }, { signal });
    frameId = window.requestAnimationFrame(render);
    signal.addEventListener('abort', () => window.cancelAnimationFrame(frameId), { once: true });
  }

  /* ---------------------------------------------------------------- */
  /* Reduced motion + page-leave transition                            */
  /* ---------------------------------------------------------------- */
  function initReducedMotion() {
    if (reduceMotion.matches) document.body.classList.add('is-intro-reduced');
  }

  try {
    initReducedMotion();
    initIntroMotion();
    initAthleteSwitcher();
    initCanvasTrajectories();
    initPointerParallax();

    window.addEventListener('pagehide', (event) => {
      clearTimeline();
      window.clearTimeout(resizeTimer);
      // 뒤로가기 캐시에 저장되는 페이지는 같은 JS 인스턴스가 그대로
      // 복원된다. 이때 이벤트까지 abort하면 다시 보기와 자동 모션이
      // 영구적으로 사라지므로 실제 폐기되는 경우에만 정리한다.
      if (!event.persisted) controller.abort();
    });
  } catch (error) {
    clearTimeline();
    for (let i = 1; i <= 7; i += 1) document.body.classList.add(`is-intro-scene-${i}`);
    document.body.classList.add('is-intro-settled');
  }
})();

/* ---------------------------------------------------------------- */
/* Iris clip-path preview / page transition (recommend panels)       */
/* ---------------------------------------------------------------- */
(() => {
  'use strict';

  const panels = document.querySelectorAll('.recommend-panel[data-iris-target]');
  if (!panels.length) return;

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const PEEK_RADIUS = 250;

  panels.forEach((panel) => {
    const layer = document.querySelector(`.iris-layer[data-iris-layer="${panel.dataset.irisTarget}"]`);
    const preview = panel.querySelector('[data-panel-preview]');
    const frame = preview ? preview.querySelector('[data-iris-frame]') : null;
    const coverFrame = layer ? layer.querySelector('[data-iris-cover-frame]') : null;
    const brand = layer ? layer.querySelector('.iris-layer-brand') : null;
    if (!layer) return;

    let navigating = false;

    function loadFrame(el) {
      if (!el || el.dataset.loaded) return;
      el.dataset.loaded = '1';
      el.src = el.dataset.src;
    }

    // The peek circle is positioned with percentages ("at 50% 50%") relative
    // to the button's own box, which .recommend-panel's overflow: hidden also
    // clips — so it can never bleed past the button edge, and it stays put
    // on scroll without any JS position tracking.
    function setPeek(active) {
      if (!preview || reduceMotion.matches || navigating) return;
      if (active) { loadFrame(frame); loadFrame(coverFrame); }
      preview.classList.add('is-active');
      preview.style.clipPath = `circle(${active ? PEEK_RADIUS : 0}px at 50% 50%)`;
    }

    panel.addEventListener('mouseenter', () => setPeek(true));
    panel.addEventListener('mouseleave', () => setPeek(false));
    panel.addEventListener('focus', () => setPeek(true));
    panel.addEventListener('blur', () => setPeek(false));

    panel.addEventListener('click', (event) => {
      if (reduceMotion.matches || navigating) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
      const href = panel.getAttribute('href');
      if (!href) return;

      event.preventDefault();
      navigating = true;
      if (preview) {
        preview.style.transition = 'none';
        preview.style.clipPath = 'circle(0px at 50% 50%)';
        void preview.offsetWidth;
        preview.style.transition = '';
      }
      loadFrame(coverFrame);

      // Anchor at the same point the hover-peek circle used (the button's own
      // center — that's what "at 50% 50%" resolves to on .panel-preview), not
      // the raw click position, so the click-expand continues from exactly
      // where the peek circle already was instead of jumping to the cursor.
      const rect = panel.getBoundingClientRect();
      const x = rect.left + rect.width / 2;
      const y = rect.top + rect.height / 2;
      const fullRadius = Math.hypot(window.innerWidth, window.innerHeight);

      // Snap the full-screen layer to the exact same size/position the peek
      // circle was already at, with no transition — otherwise this element
      // (starting from the class's default circle(0px)) would itself animate
      // 0 → PEEK_RADIUS under the .85s transition below, growing "from
      // nothing" at the same time the peek circle collapses. That double
      // motion at the same spot is what reads as a stutter/cut. Only after
      // this instant handoff do we turn the transition on for the real
      // PEEK_RADIUS → fullRadius expansion.
      layer.style.transition = 'none';
      layer.style.clipPath = `circle(${PEEK_RADIUS}px at ${x}px ${y}px)`;
      void layer.offsetWidth;
      layer.style.transition = '';
      layer.classList.add('is-transitioning-cover');
      if (brand) brand.classList.add('is-loading');

      const goToTarget = () => { window.location.href = href; };
      let settled = false;
      function onTransitionEnd(transitionEvent) {
        if (transitionEvent.propertyName !== 'clip-path' || settled) return;
        settled = true;
        layer.removeEventListener('transitionend', onTransitionEnd);
        goToTarget();
      }
      layer.addEventListener('transitionend', onTransitionEnd);
      // Fallback in case transitionend never fires (e.g. layout thrash mid-transition).
      window.setTimeout(() => { if (!settled) { settled = true; goToTarget(); } }, 1000);

      requestAnimationFrame(() => {
        requestAnimationFrame(() => { layer.style.clipPath = `circle(${fullRadius}px at ${x}px ${y}px)`; });
      });
    });

    // A page a user reaches via Back/Forward after we navigated away mid-transition
    // may be served from bfcache with the circle still frozen mid-expansion — reset it.
    window.addEventListener('pageshow', (event) => {
      if (!event.persisted) return;
      navigating = false;
      if (preview) { preview.classList.remove('is-active'); preview.style.removeProperty('clip-path'); }
      if (brand) brand.classList.remove('is-loading');
      layer.classList.remove('is-transitioning-cover');
      layer.style.transition = 'none';
      layer.style.removeProperty('clip-path');
      void layer.offsetWidth;
      layer.style.transition = '';
      [frame, coverFrame].forEach((el) => {
        if (!el) return;
        el.removeAttribute('src');
        el.src = 'about:blank';
        delete el.dataset.loaded;
      });
    });
  });
})();
