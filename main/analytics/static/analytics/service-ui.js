(() => {
  'use strict';

  if (window.Chart) {
    Chart.defaults.color = '#a5a6ae';
    Chart.defaults.borderColor = 'rgba(245,245,242,.11)';
    Chart.defaults.font.family = 'Pretendard, "Noto Sans KR", system-ui, sans-serif';
    Chart.defaults.plugins.legend.labels.color = '#d8d9de';
  }

  document.querySelectorAll('select').forEach((select) => {
    select.style.colorScheme = 'dark';
  });
})();
