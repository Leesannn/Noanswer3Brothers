(() => {
  'use strict';

  document.querySelectorAll('.demand-supply-page select').forEach((select) => {
    select.style.colorScheme = 'light';
  });

  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  document.querySelectorAll('[data-ds-count]').forEach((element) => {
    const target = Number(element.dataset.dsCount);
    if (!Number.isFinite(target)) return;

    const startedAt = performance.now();
    const duration = 760;

    const render = (now) => {
      const progress = Math.min((now - startedAt) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const value = target * eased;
      element.textContent = Math.round(value).toLocaleString('ko-KR');
      if (progress < 1) requestAnimationFrame(render);
    };

    requestAnimationFrame(render);
  });
})();
