/* SWIFT landing — interactions
   1. Scroll-reveal for blocks marked .reveal
   2. Endless marquee for the two "Built on open data" ribbons
   3. Smooth in-page navigation that respects reduced motion */
(function () {
  'use strict';

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- 1. Scroll reveal ---------- */
  const revealEls = document.querySelectorAll('.reveal');
  if (!('IntersectionObserver' in window) || reduceMotion) {
    revealEls.forEach((el) => el.classList.add('is-visible'));
  } else {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });
    revealEls.forEach((el) => io.observe(el));
  }

  /* ---------- 2. Ribbon marquee ---------- */
  const FIRST_ITEM_X = 70.59; // x of the first label inside the ribbon in Figma
  const SPEED = 45;           // px per second

  const tracks = Array.from(document.querySelectorAll('.ribbon__track'));
  const templates = tracks.map((t) => t.firstElementChild.cloneNode(true));

  function buildMarquee(track, template) {
    track.classList.remove('is-running');
    track.replaceChildren(template.cloneNode(true));

    const ribbonWidth = track.parentElement.offsetWidth;
    const itemWidth = track.firstElementChild.offsetWidth;
    if (!itemWidth) return;

    // One "set" must be wider than the ribbon so the loop never shows a gap.
    const perSet = Math.ceil(ribbonWidth / itemWidth) + 1;
    for (let i = 1; i < perSet * 2; i++) track.appendChild(template.cloneNode(true));

    const shift = perSet * itemWidth;
    track.style.setProperty('--start', (FIRST_ITEM_X - itemWidth) + 'px');
    track.style.setProperty('--shift', shift + 'px');
    track.style.setProperty('--dur', (shift / SPEED) + 's');
    track.style.transform = `translateX(${FIRST_ITEM_X - itemWidth}px)`;

    if (!reduceMotion) track.classList.add('is-running');
  }

  function buildAll() {
    tracks.forEach((t, i) => buildMarquee(t, templates[i]));
  }

  let resizeTimer;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(buildAll, 150);
  });

  (document.fonts ? document.fonts.ready : Promise.resolve()).then(buildAll);

  /* ---------- 3. In-page links ---------- */
  document.querySelectorAll('a[href^="#"]').forEach((link) => {
    link.addEventListener('click', (e) => {
      const id = link.getAttribute('href');
      if (id === '#') { e.preventDefault(); return; }
      const target = document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
      history.replaceState(null, '', id);
    });
  });
})();
