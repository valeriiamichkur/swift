/* Forecast Controls — Weekday / Weekend switch + forecast clock, driving the
   live station map (js/station-map.js → /api/forecast in server.py).
   Weekday state = Figma frame 135:145, Weekend state = 135:171.

   The map shows the 1-hour forecast for the window that STARTS at the clock
   time on the chosen day type: live bike counts + average net flow for that hour.
   On load the clock and the switch are set to the current New York time/day,
   so the first view matches the Streamlit stream. */
(function () {
  'use strict';

  /* ---------- Current New York time ---------- */
  function newYorkNow() {
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York', weekday: 'short', hour: 'numeric', minute: 'numeric', hourCycle: 'h23',
    }).formatToParts(new Date()).map((p) => [p.type, p.value]));
    return {
      hours24: Number(parts.hour) % 24,
      minutes: Number(parts.minute),
      dayType: parts.weekday === 'Sat' || parts.weekday === 'Sun' ? 'weekend' : 'weekday',
    };
  }

  const now = newYorkNow();
  const state = { dayType: 'weekday' };

  /* ---------- Map ---------- */
  const fmt = SwiftStationMap.formatTime;
  const summary = {
    window: document.getElementById('summary-window'),
    low: document.getElementById('summary-low'),
    high: document.getElementById('summary-high'),
    note: document.getElementById('summary-note'),
  };
  const stationMap = window.L && window.SwiftStationMap
    ? new SwiftStationMap(document.getElementById('station-map'))
    : null;

  function renderSummary(data) {
    const day = data.day === 'weekend' ? 'weekend' : 'weekday';
    summary.window.textContent = `${fmt(data.window.start)} – ${fmt(data.window.end)} · ${day}`;
    summary.low.textContent = data.counts.low.toLocaleString('en-US');
    summary.high.textContent = data.counts.high.toLocaleString('en-US');
    const h = data.history;
    summary.note.classList.toggle('is-warn', data.is_backup);
    summary.note.textContent = (data.is_backup
      ? `Live feed unavailable: backup bike counts from ${fmt(data.as_of)}. `
      : `Bike counts live as of ${fmt(data.as_of)}. `)
      + `Naive estimate: counts now + average net flow for that hour over ${h.days[day] ?? '?'} ${day} days `
      + `(${h.first_day} to ${h.last_day}). Not a guarantee.`;
  }

  let clock = null;
  function refresh() {
    if (!stationMap || !clock) return;
    const time = clock.getTime();
    summary.window.textContent = `${time.label} · ${state.dayType}`;
    stationMap.load({ day: state.dayType, time: time.value })
      .then((data) => data && renderSummary(data))
      .catch((err) => {
        summary.note.classList.add('is-warn');
        summary.note.textContent = location.protocol === 'file:'
          ? 'Start the site with python3 server.py to load live stations.'
          : `Could not load the forecast: ${err.message}`;
      });
  }

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
    refresh();
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
    refresh();
    return time;
  }

  const startMinutes = Math.floor(now.minutes / 5) * 5;
  clock = new ForecastClock(document.getElementById('forecast-clock'), {
    hours: now.hours24 % 12 || 12,
    minutes: startMinutes,
    period: now.hours24 < 12 ? 'AM' : 'PM',
    onTimeSet,
    // While the hand moves, preview the time in the summary; the map updates on release.
    onChange: (time) => { summary.window.textContent = `${time.label} · ${state.dayType}`; },
  });

  // Start on today's day type; selectDayType() loads the first forecast when it switches.
  if (now.dayType !== state.dayType) selectDayType(now.dayType);
  else refresh();

  // Bike counts change all the time: re-forecast every minute while the tab is visible.
  setInterval(() => { if (!document.hidden) refresh(); }, 60000);

  // Public API for other scripts / the console:
  //   SWIFT.getForecastTime()   → current clock time
  //   SWIFT.setForecastTime(17, 30)
  //   document.addEventListener('forecast:timeset', e => e.detail)
  window.SWIFT = Object.assign(window.SWIFT || {}, {
    getForecastTime: () => clock.getTime(),
    setForecastTime: (h24, m) => { const t = clock.setTime(h24, m); refresh(); return t; },
    getDayType: () => state.dayType,
    stationMap,
  });
})();
