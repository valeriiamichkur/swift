/* Forecast Controls — Weekday / Weekend switch + forecast clock.
   Weekday state = Figma frame 135:145, Weekend state = 135:171. */
(function () {
  'use strict';

  const state = { dayType: 'weekday' };

  /* ---------- Weekday / Weekend ---------- */
  const segments = document.querySelectorAll('.segment');

  function selectDayType(type) {
    if (type === state.dayType) return;
    state.dayType = type;
    segments.forEach((seg) => {
      const on = seg.dataset.mode === type;
      seg.classList.toggle('is-active', on);
      seg.setAttribute('aria-selected', String(on));
    });
  }

  segments.forEach((seg) => seg.addEventListener('click', () => selectDayType(seg.dataset.mode)));

  document.querySelector('.segments').addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const other = Array.from(segments).find((s) => s !== document.activeElement);
    if (!other) return;
    other.focus();
    other.click();
    e.preventDefault();
  });

  /* ---------- Clock ---------- */

  /**
   * Called once the user has FINISHED changing the time:
   * after releasing the hand, after the last arrow-key press,
   * or after switching AM/PM. Only fires when the time actually changed.
   *
   * @param {ForecastTime} time  e.g. { hours: 3, minutes: 15, period: 'PM',
   *                             hours24: 15, value: '15:15', label: '3:15 PM' }
   * @returns {ForecastTime}     the time the clock was set to
   */
  function onTimeSet(time) {
    console.log('[SWIFT] forecast time set:', time.label, `(${time.value})`, '·', state.dayType);
    // Hook the forecast request in here, e.g.
    // fetch(`/api/forecast?day=${state.dayType}&time=${time.value}`)
    return time;
  }

  const clock = new ForecastClock(document.getElementById('forecast-clock'), {
    hours: 12,
    minutes: 0,
    period: 'AM',
    onTimeSet,
  });

  // Public API for other scripts / the console:
  //   SWIFT.getForecastTime()   → current clock time
  //   SWIFT.setForecastTime(17, 30)
  //   document.addEventListener('forecast:timeset', e => e.detail)
  window.SWIFT = Object.assign(window.SWIFT || {}, {
    getForecastTime: () => clock.getTime(),
    setForecastTime: (h24, m) => clock.setTime(h24, m),
    getDayType: () => state.dayType,
  });
})();
