(() => {
  'use strict';

  var root = document.querySelector('[data-motion-root]');
  if (!root) return;

  // Keyed per page (not shared across unlicensed/licensed) so visiting the
  // other condition-input page still shows its own intro at least once.
  var SESSION_KEY = 'recommendationFormIntroPlayed:' + window.location.pathname;
  var reduceMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  var desktopPointerQuery = window.matchMedia('(hover: hover) and (pointer: fine)');

  var runnerImg = root.querySelector('[data-collage-runner]');
  var circleImg = root.querySelector('[data-collage-circle]');
  var skipBtn = root.querySelector('[data-motion-skip]');
  var replayBtn = root.querySelector('[data-motion-replay]');

  var timers = [];

  function isMobile() {
    return window.innerWidth <= 700;
  }

  function schedule(fn, delay) {
    timers.push(window.setTimeout(fn, delay));
  }

  function clearTimers() {
    timers.forEach(function (id) { window.clearTimeout(id); });
    timers.length = 0;
  }

  function clearStages() {
    ['step', 'heading', 'collage', 'form', 'fields', 'cta', 'settled'].forEach(function (name) {
      root.classList.remove('is-motion-' + name);
    });
  }

  function setStage(name) {
    root.classList.add('is-motion-' + name);
  }

  // ---- scripted intro timeline (one-time reveal; the hero's breathing/pulse/
  // drift/dot-flow loops are pure CSS animations gated by .is-motion-collage) ----
  function runIntroTimeline() {
    clearTimers();
    clearStages();

    var mobile = isMobile();
    var timing = mobile
      ? { heading: 120, collage: 360, form: 380, fields: 480, cta: 1250, settle: 1850 }
      : { heading: 200, collage: 650, form: 750, fields: 900, cta: 2000, settle: 2600 };

    setStage('step');
    schedule(function () { setStage('heading'); }, timing.heading);
    schedule(function () { setStage('collage'); }, timing.collage);
    schedule(function () { setStage('form'); }, timing.form);
    schedule(function () { setStage('fields'); }, timing.fields);
    schedule(function () { setStage('cta'); }, timing.cta);
    schedule(function () {
      setStage('settled');
      try { window.sessionStorage.setItem(SESSION_KEY, 'true'); } catch (error) { /* private mode */ }
    }, timing.settle);
  }

  function settleInstant() {
    clearTimers();
    ['step', 'heading', 'collage', 'form', 'fields', 'cta', 'settled'].forEach(setStage);
  }

  // ---- skip / replay controls ----
  function initControls() {
    if (skipBtn) {
      skipBtn.addEventListener('click', function () {
        settleInstant();
        try { window.sessionStorage.setItem(SESSION_KEY, 'true'); } catch (error) { /* private mode */ }
        skipBtn.hidden = true;
        if (replayBtn) replayBtn.hidden = reduceMotionQuery.matches;
      });
    }
    if (replayBtn) {
      replayBtn.addEventListener('click', function () {
        if (reduceMotionQuery.matches) return;
        replayBtn.hidden = true;
        if (skipBtn) skipBtn.hidden = false;
        runIntroTimeline();
      });
    }
  }

  // ---- desktop-only pointer parallax on runner + circle (max 8px / 4px) ----
  function initParallax() {
    if (!desktopPointerQuery.matches) return;
    document.addEventListener('mousemove', function (event) {
      if (isMobile() || reduceMotionQuery.matches) return;
      var relX = event.clientX / window.innerWidth - .5;
      var relY = event.clientY / window.innerHeight - .5;
      if (runnerImg) {
        runnerImg.style.setProperty('--parallax-x', (relX * 8).toFixed(1) + 'px');
        runnerImg.style.setProperty('--parallax-y', (relY * 8).toFixed(1) + 'px');
      }
      if (circleImg) {
        circleImg.style.setProperty('--parallax-x', (relX * 4).toFixed(1) + 'px');
        circleImg.style.setProperty('--parallax-y', (relY * 4).toFixed(1) + 'px');
      }
    }, { passive: true });
  }

  // ---- field fill feedback (border + dot + one-shot chip pulse) ----
  function initFieldFeedback() {
    var selects = root.querySelectorAll('.recommend-field select');
    selects.forEach(function (select) {
      var wrapper = select.closest('.recommend-field');
      if (!wrapper) return;
      var chip = wrapper.querySelector('.required-chip');
      function sync() {
        wrapper.classList.toggle('is-filled', !!select.value);
      }
      sync();
      select.addEventListener('change', function () {
        sync();
        if (chip && select.value) {
          chip.classList.remove('chip-pulse');
          void chip.offsetWidth;
          chip.classList.add('chip-pulse');
        }
      });
    });
  }

  initControls();
  initParallax();
  initFieldFeedback();

  window.addEventListener('pageshow', function (event) {
    if (event.persisted) settleInstant();
  });

  var alreadyPlayed = false;
  try { alreadyPlayed = window.sessionStorage.getItem(SESSION_KEY) === 'true'; } catch (error) { /* private mode */ }

  if (reduceMotionQuery.matches) {
    settleInstant();
    if (skipBtn) skipBtn.hidden = true;
  } else if (alreadyPlayed) {
    settleInstant();
    if (skipBtn) skipBtn.hidden = true;
    if (replayBtn) replayBtn.hidden = false;
  } else {
    runIntroTimeline();
  }
})();
