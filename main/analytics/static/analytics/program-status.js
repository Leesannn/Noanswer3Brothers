(() => {
  'use strict';

  document.querySelectorAll('.program-status-page select').forEach((select) => {
    select.style.colorScheme = 'light';
  });

  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  document.querySelectorAll('[data-program-count]').forEach((element) => {
    const target = Number(element.dataset.programCount);
    if (!Number.isFinite(target)) return;

    const decimals = Number(element.dataset.programDecimals || 0);
    const suffix = element.dataset.programSuffix || '';
    const startedAt = performance.now();
    const duration = 760;

    const render = (now) => {
      const progress = Math.min((now - startedAt) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const value = target * eased;
      element.textContent = value.toLocaleString('ko-KR', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      }) + suffix;
      if (progress < 1) requestAnimationFrame(render);
    };

    requestAnimationFrame(render);
  });
})();
