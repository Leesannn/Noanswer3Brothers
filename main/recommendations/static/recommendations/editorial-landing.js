(() => {
  'use strict';

  const root = document.querySelector('[data-motion-root]');
  if (!root) return;

  const canvas = root.querySelector('[data-particle-canvas]');
  const context = canvas && canvas.getContext ? canvas.getContext('2d') : null;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const compactMotion = window.matchMedia('(max-width: 700px)');
  const precisePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
  const sessionKey = 'sportsCareerMotionPlayed';
  const sceneClasses = ['scene-1', 'scene-2', 'scene-3', 'scene-4', 'scene-5', 'scene-6'];
  const sportScenes = {
    data: { scene: 1, accent: '#f5f5f2' },
    athlete: { scene: 2, accent: '#91f5d2' },
    sports: { scene: 3, accent: '#5b7cff' },
    qualification: { scene: 4, accent: '#5b7cff' },
    opportunity: { scene: 5, accent: '#91f5d2' },
    settled: { scene: 6, accent: '#5b7cff' },
  };
  const controller = new AbortController();
  const signal = controller.signal;
  const timeouts = [];
  const pointer = { targetX: 0, targetY: 0, x: 0, y: 0 };
  let frameId = 0;
  let resizeTimer = 0;
  let scrollFrame = 0;
  let heroVisible = true;
  let pageVisible = !document.hidden;
  let particles = [];
  let width = 0;
  let height = 0;
  let dpr = 1;

  function safeSessionGet() {
    try { return sessionStorage.getItem(sessionKey); } catch (error) { return null; }
  }

  function safeSessionSet() {
    try { sessionStorage.setItem(sessionKey, '1'); } catch (error) { /* storage is optional */ }
  }

  function clearTimeline() {
    while (timeouts.length) window.clearTimeout(timeouts.pop());
  }

  function setCaption(scene) {
    root.querySelectorAll('[data-scene-caption]').forEach((caption) => {
      caption.classList.toggle('is-active', Number(caption.dataset.sceneCaption) === scene);
    });
  }

  function setScene(scene) {
    root.classList.remove(...sceneClasses);
    root.classList.add(`scene-${scene}`);
    root.style.setProperty('--scene-progress', `${Math.min(100, scene / 6 * 100)}%`);
    setCaption(scene);
  }

  function settle(state = 'settled') {
    clearTimeline();
    setScene(sportScenes.settled.scene);
    root.dataset.motionState = state;
    safeSessionSet();
  }

  function playIntro() {
    clearTimeline();
    root.classList.remove('is-leaving');
    root.dataset.motionState = 'intro';
    const timing = compactMotion.matches
      ? [[1, 0], [2, 380], [3, 950], [4, 1500], [5, 2150], [6, 2700]]
      : [[1, 0], [2, 1000], [3, 2500], [4, 4000], [5, 5000], [6, 6000]];

    timing.forEach(([scene, delay]) => {
      timeouts.push(window.setTimeout(() => setScene(scene), delay));
    });
    timeouts.push(window.setTimeout(() => settle('settled'), compactMotion.matches ? 3000 : 7000));
  }

  function createParticles() {
    const total = compactMotion.matches ? 12 : 30;
    particles = Array.from({ length: total }, (_, index) => ({
      x: ((index * 47) % 101) / 100 * width,
      y: ((index * 73 + 17) % 103) / 102 * height,
      vx: ((index % 5) - 2) * .045,
      vy: (((index * 3) % 5) - 2) * .032,
      radius: index % 7 === 0 ? 1.8 : 1,
      phase: index * .73,
    }));
  }

  function resizeCanvas() {
    if (!context || !canvas) return;
    const bounds = root.getBoundingClientRect();
    width = Math.max(1, Math.round(bounds.width));
    height = Math.max(1, Math.round(bounds.height));
    dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    createParticles();
  }

  function drawParticles(now) {
    if (!context || !pageVisible || !heroVisible) return;
    context.clearRect(0, 0, width, height);
    const settledMotion = root.dataset.motionState !== 'intro';
    const pull = root.classList.contains('scene-1') ? .0018 : 0;
    const centerX = width * .58;
    const centerY = height * .43;

    particles.forEach((particle, index) => {
      if (!reduceMotion.matches) {
        particle.x += particle.vx + Math.sin(now * .00032 + particle.phase) * (settledMotion ? .018 : .05);
        particle.y += particle.vy + Math.cos(now * .00028 + particle.phase) * (settledMotion ? .015 : .04);
        particle.x += (centerX - particle.x) * pull;
        particle.y += (centerY - particle.y) * pull;
      }
      if (particle.x < -10) particle.x = width + 10;
      if (particle.x > width + 10) particle.x = -10;
      if (particle.y < -10) particle.y = height + 10;
      if (particle.y > height + 10) particle.y = -10;

      context.beginPath();
      context.fillStyle = index % 9 === 0 ? 'rgba(91,124,255,.78)' : 'rgba(245,245,242,.55)';
      context.arc(particle.x + pointer.x * .18, particle.y + pointer.y * .18, particle.radius, 0, Math.PI * 2);
      context.fill();
    });

    for (let i = 0; i < particles.length; i += 1) {
      for (let j = i + 1; j < particles.length; j += 1) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const distance = Math.sqrt(dx * dx + dy * dy);
        if (distance < 130) {
          context.beginPath();
          context.strokeStyle = `rgba(245,245,242,${(1 - distance / 130) * .12})`;
          context.lineWidth = .6;
          context.moveTo(particles[i].x, particles[i].y);
          context.lineTo(particles[j].x, particles[j].y);
          context.stroke();
        }
      }
    }
  }

  function render(now) {
    frameId = 0;
    if (!pageVisible || !heroVisible || reduceMotion.matches) return;
    pointer.x += (pointer.targetX - pointer.x) * .055;
    pointer.y += (pointer.targetY - pointer.y) * .055;
    root.querySelectorAll('.parallax-layer').forEach((layer) => {
      const depth = Number(layer.dataset.depth || 8) / 16;
      layer.style.setProperty('--layer-x', `${(pointer.x * depth).toFixed(2)}px`);
      layer.style.setProperty('--layer-y', `${(pointer.y * depth).toFixed(2)}px`);
    });
    drawParticles(now);
    frameId = window.requestAnimationFrame(render);
  }

  function syncRender() {
    if (reduceMotion.matches) {
      window.cancelAnimationFrame(frameId);
      frameId = 0;
      drawParticles(0);
      return;
    }
    if (pageVisible && heroVisible && !frameId) frameId = window.requestAnimationFrame(render);
    if ((!pageVisible || !heroVisible) && frameId) {
      window.cancelAnimationFrame(frameId);
      frameId = 0;
    }
  }

  function updateScroll() {
    scrollFrame = 0;
    const bounds = root.getBoundingClientRect();
    const progress = Math.max(0, Math.min(1, -bounds.top / Math.max(1, bounds.height * .72)));
    root.style.setProperty('--scroll-progress', progress.toFixed(3));
    const paths = document.querySelector('.service-paths');
    if (paths) {
      paths.style.setProperty('--bridge-x', `${(progress * 110).toFixed(1)}px`);
      paths.style.setProperty('--bridge-y', `${(progress * 160).toFixed(1)}px`);
    }
  }

  function onPointerMove(event) {
    if (!precisePointer.matches || reduceMotion.matches) return;
    pointer.targetX = Math.max(-16, Math.min(16, (event.clientX / window.innerWidth - .5) * 24));
    pointer.targetY = Math.max(-12, Math.min(12, (event.clientY / window.innerHeight - .5) * 18));
  }

  function handleTransition(event) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || reduceMotion.matches) return;
    const link = event.currentTarget;
    const url = link.href;
    if (!url) return;
    event.preventDefault();
    safeSessionSet();
    root.dataset.leaveTarget = link.dataset.target || 'qualification';
    root.classList.add('is-leaving');
    window.setTimeout(() => window.location.assign(url), 360);
  }

  try {
    root.classList.add('motion-ready');
    resizeCanvas();
    updateScroll();

    root.querySelector('[data-motion-skip]')?.addEventListener('click', () => settle('skipped'), { signal });
    root.querySelector('[data-motion-replay]')?.addEventListener('click', playIntro, { signal });
    root.querySelectorAll('[data-transition-link]').forEach((link) => link.addEventListener('click', handleTransition, { signal }));
    window.addEventListener('pointermove', onPointerMove, { passive: true, signal });
    window.addEventListener('scroll', () => {
      if (!scrollFrame) scrollFrame = window.requestAnimationFrame(updateScroll);
    }, { passive: true, signal });
    window.addEventListener('resize', () => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => { resizeCanvas(); updateScroll(); }, 140);
    }, { passive: true, signal });
    document.addEventListener('visibilitychange', () => { pageVisible = !document.hidden; syncRender(); }, { signal });
    window.addEventListener('pageshow', (event) => { if (event.persisted) settle('settled'); }, { signal });
    window.addEventListener('pagehide', () => {
      clearTimeline();
      window.cancelAnimationFrame(frameId);
      window.cancelAnimationFrame(scrollFrame);
      window.clearTimeout(resizeTimer);
      controller.abort();
    }, { once: true });

    if ('IntersectionObserver' in window) {
      const observer = new IntersectionObserver((entries) => { heroVisible = entries[0]?.isIntersecting ?? true; syncRender(); }, { threshold: 0 });
      observer.observe(root);
      signal.addEventListener('abort', () => observer.disconnect(), { once: true });
    }

    syncRender();
    if (reduceMotion.matches) {
      setScene(6);
      root.dataset.motionState = 'reduced-motion';
    } else if (safeSessionGet()) {
      settle('settled');
    } else {
      playIntro();
    }
  } catch (error) {
    clearTimeline();
    root.classList.add('motion-ready', 'scene-6');
    root.dataset.motionState = 'error';
  }
})();
