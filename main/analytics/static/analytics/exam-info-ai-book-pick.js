/*
 * 시험정보 페이지 "AI 추천 교재" 접이식 섹션.
 *
 * 자격 등급 탭은 페이지 전체를 새로 불러오는 서버 렌더링 방식(?grade=CODE)이라
 * 자바스크립트 쪽 상태는 "이 섹션이 열려 있었는지"만 sessionStorage에 남겨서,
 * 탭을 바꿔 페이지가 새로고침돼도 열려 있던 패널은 새 자격증 기준으로 다시
 * 펼쳐지고 자동으로 재요청하도록 한다. 실제 추천 결과 캐시(24시간)는 서버가
 * 자격증 코드별로 들고 있으므로 같은 등급을 다시 열면 캐시가 그대로 쓰인다.
 */
(() => {
  'use strict';

  const root = document.querySelector('[data-ai-pick]');
  if (!root) return;

  const toggle = root.querySelector('[data-ai-pick-toggle]');
  const panel = root.querySelector('[data-ai-pick-panel]');
  const body = root.querySelector('[data-ai-pick-body]');
  const toggleLabel = root.querySelector('[data-ai-pick-toggle-label]');
  const dataEl = document.getElementById('exam-ai-pick-data');
  if (!toggle || !panel || !body || !dataEl) return;

  let context;
  try {
    context = JSON.parse(dataEl.textContent);
  } catch (error) {
    context = { certificationId: '', certificationName: '', writtenSubjects: [] };
  }

  const SESSION_KEY = 'examAiPickOpen';
  const ENDPOINT = '/api/book-recommendations/';

  let loaded = false;
  let loading = false;

  function getCookie(name) {
    const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : '';
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function coverPlaceholder(title, isSmall) {
    const cover = el('div', 'exam-ai-pick-cover' + (isSmall ? ' exam-ai-pick-cover-also' : ''));
    const spine = el('div', 'exam-ai-pick-cover-spine');
    spine.appendChild(el('span', null, 'BOOK PICK'));
    const body = el('div', 'exam-ai-pick-cover-body');
    body.appendChild(el('span', null, title));
    cover.appendChild(spine);
    cover.appendChild(body);
    return cover;
  }

  function setOpen(open) {
    root.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (toggleLabel) toggleLabel.textContent = open ? '접기' : '펼치기';
    if (open) panel.removeAttribute('inert');
    else panel.setAttribute('inert', '');
    try { sessionStorage.setItem(SESSION_KEY, open ? '1' : '0'); } catch (error) { /* storage optional */ }
  }

  function renderLoading() {
    clear(body);
    const grid = el('div', 'exam-ai-pick-grid');

    const best = el('div');
    best.appendChild(el('div', 'exam-ai-pick-skel exam-ai-pick-skel-cover'));
    ['70%', '45%', '92%', '88%'].forEach((w) => {
      const line = el('div', 'exam-ai-pick-skel exam-ai-pick-skel-line');
      line.style.width = w;
      best.appendChild(line);
    });

    const also = el('div');
    for (let i = 0; i < 2; i += 1) {
      const line = el('div', 'exam-ai-pick-skel exam-ai-pick-skel-line');
      line.style.width = '80%';
      also.appendChild(line);
    }

    grid.appendChild(best);
    grid.appendChild(also);
    body.appendChild(grid);
    body.appendChild(el('p', 'exam-ai-pick-loading-text', 'Gemini가 교재를 고르는 중…'));
  }

  function renderError() {
    clear(body);
    const wrap = el('div', 'exam-ai-pick-error');
    wrap.appendChild(el('p', null, '추천을 불러오지 못했어요'));
    const retry = el('button', 'exam-ai-pick-retry', '다시 시도');
    retry.type = 'button';
    retry.addEventListener('click', () => fetchPicks(false));
    wrap.appendChild(retry);
    body.appendChild(wrap);
  }

  function buildBest(data, bookstoreUrl) {
    const wrap = el('div');
    wrap.appendChild(el('span', 'exam-ai-pick-best-label', 'BEST MATCH'));

    const layout = el('div', 'exam-ai-pick-best');
    layout.appendChild(coverPlaceholder(data.title, false));

    const info = el('div');
    info.appendChild(el('h3', 'exam-ai-pick-best-title', data.title));
    info.appendChild(el('p', 'exam-ai-pick-best-meta', `${data.author} · ${data.publisher} · ${data.year}`));
    info.appendChild(el('p', 'exam-ai-pick-best-reason', data.reason));

    const chips = el('div', 'exam-ai-pick-chips');
    (data.coveredSubjects || []).forEach((subject) => {
      const chip = el('span', 'exam-ai-pick-chip');
      chip.appendChild(el('b', null, '✓'));
      chip.appendChild(document.createTextNode(subject));
      chips.appendChild(chip);
    });
    info.appendChild(chips);

    const actions = el('div', 'exam-ai-pick-actions');
    const buyLink = el('a', 'exam-ai-pick-buy', '서점에서 보기 ↗');
    buyLink.href = bookstoreUrl;
    buyLink.target = '_blank';
    buyLink.rel = 'noopener noreferrer';
    actions.appendChild(buyLink);

    const retryBest = el('button', 'exam-ai-pick-retry-best', '다른 책 추천');
    retryBest.type = 'button';
    retryBest.addEventListener('click', () => fetchPicks(true));
    actions.appendChild(retryBest);
    info.appendChild(actions);

    layout.appendChild(info);
    wrap.appendChild(layout);
    return wrap;
  }

  function buildAlsoGood(items) {
    const wrap = el('div');
    wrap.appendChild(el('span', 'exam-ai-pick-also-label', 'ALSO GOOD'));
    const list = el('ul', 'exam-ai-pick-also-list');
    items.forEach((item) => {
      const li = el('li', 'exam-ai-pick-also-item');
      li.appendChild(coverPlaceholder(item.title, true));
      const info = el('div');
      info.appendChild(el('p', 'exam-ai-pick-also-title', item.title));
      info.appendChild(el('p', 'exam-ai-pick-also-meta', `${item.author} · ${item.category}`));
      info.appendChild(el('p', 'exam-ai-pick-also-reason', item.reason));
      li.appendChild(info);
      list.appendChild(li);
    });
    wrap.appendChild(list);
    return wrap;
  }

  function renderSuccess(payload) {
    clear(body);
    const grid = el('div', 'exam-ai-pick-grid');
    const bookstoreUrls = payload.bookstoreUrls || {};
    grid.appendChild(buildBest(payload.bestMatch, bookstoreUrls.bestMatch || '#'));
    grid.appendChild(buildAlsoGood(payload.alsoGood || []));
    body.appendChild(grid);
  }

  function fetchPicks(refresh) {
    if (loading) return;
    loading = true;
    renderLoading();

    fetch(ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCookie('csrftoken'),
      },
      credentials: 'same-origin',
      body: JSON.stringify({
        certificationId: context.certificationId,
        certificationName: context.certificationName,
        writtenSubjects: context.writtenSubjects,
        refresh: Boolean(refresh),
      }),
    })
      .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
      .then(({ ok, data }) => {
        loading = false;
        if (!ok || data.error || !data.bestMatch) {
          renderError();
          return;
        }
        loaded = true;
        renderSuccess(data);
      })
      .catch(() => {
        loading = false;
        renderError();
      });
  }

  toggle.addEventListener('click', () => {
    const nextOpen = !root.classList.contains('is-open');
    setOpen(nextOpen);
    if (nextOpen && !loaded) fetchPicks(false);
  });

  let wasOpen = false;
  try { wasOpen = sessionStorage.getItem(SESSION_KEY) === '1'; } catch (error) { wasOpen = false; }
  if (wasOpen) {
    setOpen(true);
    fetchPicks(false);
  }
})();
