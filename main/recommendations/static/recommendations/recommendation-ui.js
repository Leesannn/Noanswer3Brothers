(() => {
  'use strict';
  const controller = new AbortController();
  const signal = controller.signal;

  document.querySelectorAll('.checkbox-field input[type="checkbox"]').forEach((box) => {
    const label = box.closest('label');
    if (!label) return;
    const sync = () => label.classList.toggle('is-checked', box.checked);
    sync();
    box.addEventListener('change', sync, { signal });
  });

  document.querySelectorAll('[data-loading-form]').forEach((form) => {
    form.addEventListener('submit', () => {
      if (!form.checkValidity()) return;
      const button = form.querySelector('button[type="submit"]');
      if (!button) return;
      button.classList.add('is-loading');
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
    }, { signal });
  });

  window.addEventListener('pagehide', () => controller.abort(), { once: true });
})();
