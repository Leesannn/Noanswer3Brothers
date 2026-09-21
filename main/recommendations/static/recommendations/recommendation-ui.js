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

  // A page reached via Back/Forward after a submit navigated away can be
  // served from bfcache with the submit button frozen in its loading state
  // (disabled, spinning forever) — reset it. Not bound to `signal`: pagehide
  // above already aborts that controller before the page freezes into
  // bfcache, so a signal-bound listener here would already be gone by the
  // time this fires on restore.
  window.addEventListener('pageshow', (event) => {
    if (!event.persisted) return;
    document.querySelectorAll('[data-loading-form] button[type="submit"]').forEach((button) => {
      button.classList.remove('is-loading');
      button.disabled = false;
      button.removeAttribute('aria-busy');
    });
  });
})();
