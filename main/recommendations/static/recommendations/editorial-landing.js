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
    window.addEventListener('pageshow', (event) => { if (event.persisted) settle('settled'); }, { signal });

    if (reduceMotion.matches) {
      body.classList.add('is-intro-reduced');
    } else if (safeSessionGet()) {
      settle('settled');
    } else {
      playIntro();
    }
  }

  /* ---------------------------------------------------------------- */
  /* Athlete switcher                                                   */
  /* ---------------------------------------------------------------- */
  function initAthleteSwitcher() {
    if (!stage) return;
    const buttons = Array.from(root.querySelectorAll('[data-sport-select]'));
    const images = Array.from(stage.querySelectorAll('[data-athlete-image]'));
    if (!buttons.length || !images.length) return;

    let veil = stage.querySelector('.switch-veil');
    if (!veil) {
      veil = document.createElement('div');
      veil.className = 'switch-veil';
      veil.setAttribute('aria-hidden', 'true');
      stage.appendChild(veil);
    }

    let switching = false;

    function activate(sport, button) {
      if (switching || button.classList.contains('is-active')) return;
      const targetImage = images.find((img) => img.dataset.athleteImage === sport);
      if (!targetImage) return;

      buttons.forEach((btn) => {
        const isTarget = btn === button;
        btn.classList.toggle('is-active', isTarget);
        btn.setAttribute('aria-pressed', isTarget ? 'true' : 'false');
      });

      const shape = button.dataset.veilShape || 'slide';
      const color = button.dataset.veilColor || 'var(--editorial-blue)';
      stage.style.setProperty('--veil-color', color);
      stage.dataset.veilShape = shape;

      if (reduceMotion.matches) {
        images.forEach((img) => img.classList.toggle('is-active', img === targetImage));
        return;
      }

      switching = true;
      stage.classList.add('is-switching');
      const current = images.find((img) => img.classList.contains('is-active'));
      current?.classList.add('is-leaving');

      const swapDelay = 260;
      const endDelay = 620;
      timeouts.push(window.setTimeout(() => {
        images.forEach((img) => {
          img.classList.remove('is-leaving');
          img.classList.toggle('is-active', img === targetImage);
        });
      }, swapDelay));
      timeouts.push(window.setTimeout(() => {
        stage.classList.remove('is-switching');
        switching = false;
      }, endDelay));
    }

    buttons.forEach((button) => {
      button.addEventListener('click', () => activate(button.dataset.sportSelect, button), { signal });
    });
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
      ['[data-stage-card="qual"]', '[data-stage-float="basketball"]'],
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

  function initLeaveTransition() {
    root.querySelectorAll('[data-transition-link]').forEach((link) => {
      link.addEventListener('click', (event) => {
        if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || reduceMotion.matches) return;
        const url = link.href;
        if (!url) return;
        event.preventDefault();
        root.dataset.leaveTarget = link.dataset.target || 'qualification';
        root.classList.add('is-leaving');
        window.setTimeout(() => window.location.assign(url), 340);
      }, { signal });
    });
  }

  try {
    initReducedMotion();
    initIntroMotion();
    initAthleteSwitcher();
    initCanvasTrajectories();
    initPointerParallax();
    initLeaveTransition();

    window.addEventListener('pagehide', () => {
      clearTimeline();
      window.clearTimeout(resizeTimer);
      controller.abort();
    }, { once: true });
  } catch (error) {
    clearTimeline();
    for (let i = 1; i <= 7; i += 1) document.body.classList.add(`is-intro-scene-${i}`);
    document.body.classList.add('is-intro-settled');
  }
})();
