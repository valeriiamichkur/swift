/* ForecastClock — interactive version of the Figma clock (image 3).
   Geometry and colours are measured from the Figma export and drawn
   in a 1024 × 1024 viewBox, so it scales to any size (558px in the design).

   How it works
   - Drag the hand (or click anywhere on the dial) to set the time, 5-minute steps.
     Dragging past 12 switches AM ⇄ PM, like a real clock.
   - Click AM / PM on the switch to change the period.
   - Keyboard: focus the dial, then ← → ↑ ↓ = ±5 min, Shift or PageUp/PageDown = ±1 h,
     Home = 12:00 AM.
   - Once the user FINISHES changing the time, `onTimeSet(time)` is called and a
     `forecast:timeset` event is dispatched (detail = time).

   @typedef {Object} ForecastTime
   @property {number} hours    1–12
   @property {number} minutes  0–55
   @property {'AM'|'PM'} period
   @property {number} hours24  0–23
   @property {string} value    "HH:MM" (24-hour), e.g. "15:05"
   @property {string} label    "h:mm AM/PM",    e.g. "3:05 PM"
*/
(function (global) {
  'use strict';

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const C = 512;              // centre of the dial (viewBox units)
  const STEP = 5;             // minutes per snap
  const DAY = 24 * 60;
  const HALF = 12 * 60;

  // Measured from the Figma clock image (1024 px export)
  const G = {
    tileRadius: 58.7,         // 32px at 558px
    card: { x: 129, y: 129, size: 766, radius: 96 },
    face: { r: 317 },
    tick: { from: 284.5, to: 303.5, width: 7 },
    numberRadius: 242,
    numberSize: 60,
    timeY: 624,
    timeSize: 74,
    period: { x: 768, y: 742, w: 170, h: 65, r: 16, thumbX: 772, thumbY: 749, thumbW: 80, thumbH: 51, thumbR: 11 },
    colors: {
      tile: '#f4f2ee', card: '#ffffff', face: '#f2f3ee', faceStroke: '#dcdcda',
      ink: '#6e7583', hand: '#1a1e23', dot: '#525a63', time: '#1c1e1f',
      periodBg: '#323a40', periodThumb: '#191c22', periodOn: '#ffffff', periodOff: '#8a8f99',
    },
  };

  function el(name, attrs, parent) {
    const node = document.createElementNS(SVG_NS, name);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  }

  const mod = (n, m) => ((n % m) + m) % m;

  class ForecastClock {
    /**
     * @param {HTMLElement} root
     * @param {{hours?:number, minutes?:number, period?:'AM'|'PM', step?:number,
     *          onTimeSet?:(time:ForecastTime)=>any, onChange?:(time:ForecastTime)=>any}} [options]
     */
    constructor(root, options = {}) {
      this.root = root;
      this.step = options.step || STEP;
      this.onTimeSet = options.onTimeSet || null;
      this.onChange = options.onChange || null;

      const h12 = options.hours ?? 12;
      const period = options.period || 'AM';
      this.minutesOfDay = mod((h12 % 12) * 60 + (options.minutes || 0) + (period === 'PM' ? HALF : 0), DAY);
      this.rotation = 0;
      this.committed = this.minutesOfDay;
      this.dragging = false;
      this.keyTimer = null;

      this._build();
      this._bind();
      this._render(false);
    }

    /* ---------- public API ---------- */

    /** @returns {ForecastTime} the time the clock is currently set to */
    getTime() {
      const m = this.minutesOfDay;
      const hours24 = Math.floor(m / 60);
      const minutes = m % 60;
      const hours = hours24 % 12 || 12;
      const period = hours24 < 12 ? 'AM' : 'PM';
      const mm = String(minutes).padStart(2, '0');
      return {
        hours, minutes, period, hours24,
        value: `${String(hours24).padStart(2, '0')}:${mm}`,
        label: `${hours}:${mm} ${period}`,
      };
    }

    /** Set the time programmatically (24-hour). Does not call onTimeSet. */
    setTime(hours24, minutes = 0) {
      this.minutesOfDay = mod(Math.round((hours24 * 60 + minutes) / this.step) * this.step, DAY);
      this.committed = this.minutesOfDay;
      this._render(true);
      return this.getTime();
    }

    /**
     * Finish an edit: if the time changed since the last commit, call
     * onTimeSet and dispatch `forecast:timeset`.
     * @returns {ForecastTime} the time the clock was set to
     */
    commit() {
      const time = this.getTime();
      if (this.minutesOfDay === this.committed) return time;
      this.committed = this.minutesOfDay;
      if (this.onTimeSet) this.onTimeSet(time);
      this.root.dispatchEvent(new CustomEvent('forecast:timeset', { detail: time, bubbles: true }));
      return time;
    }

    /* ---------- drawing ---------- */

    _build() {
      const { colors: col } = G;
      const svg = el('svg', { viewBox: '0 0 1024 1024', role: 'group', 'aria-label': 'Forecast time' });

      const defs = el('defs', {}, svg);
      const filter = el('filter', { id: 'clock-card-shadow', x: '-20%', y: '-20%', width: '140%', height: '150%' }, defs);
      el('feDropShadow', { dx: 0, dy: 14, stdDeviation: 18, 'flood-color': '#000', 'flood-opacity': 0.07 }, filter);

      // Tile + white card
      el('rect', { width: 1024, height: 1024, rx: G.tileRadius, fill: col.tile }, svg);
      el('rect', {
        x: G.card.x, y: G.card.y, width: G.card.size, height: G.card.size, rx: G.card.radius,
        fill: col.card, filter: 'url(#clock-card-shadow)',
      }, svg);

      // Dial (the draggable/focusable part)
      const dial = el('g', {
        class: 'clock__dial', tabindex: 0, role: 'slider',
        'aria-label': 'Forecast time. Use arrow keys to change by 5 minutes, Shift + arrow for 1 hour.',
        'aria-valuemin': 0, 'aria-valuemax': DAY - this.step,
      }, svg);
      el('circle', { class: 'clock__face', cx: C, cy: C, r: G.face.r, fill: col.face, stroke: col.faceStroke, 'stroke-width': 2 }, dial);

      for (let i = 0; i < 12; i++) {
        const a = (i * 30 * Math.PI) / 180;
        const sin = Math.sin(a), cos = Math.cos(a);
        el('line', {
          x1: C + G.tick.from * sin, y1: C - G.tick.from * cos,
          x2: C + G.tick.to * sin,   y2: C - G.tick.to * cos,
          stroke: col.ink, 'stroke-width': G.tick.width, 'stroke-linecap': 'round',
        }, dial);
        const num = el('text', {
          class: 'clock__num',
          x: C + G.numberRadius * sin, y: C - G.numberRadius * cos,
          'text-anchor': 'middle', 'dominant-baseline': 'central',
          'font-size': G.numberSize, fill: col.ink,
        }, dial);
        num.textContent = i === 0 ? 12 : i;
      }

      this.timeText = el('text', {
        class: 'clock__time', x: C, y: G.timeY,
        'text-anchor': 'middle', 'dominant-baseline': 'central',
        'font-size': G.timeSize, fill: col.time,
      }, dial);

      // Tapered hour hand pointing to 12, rotated around the centre
      this.hand = el('g', { class: 'clock__hand' }, dial);
      el('path', {
        d: 'M492.5 512 L507 323 Q512 314 517 323 L531.5 512 A19.5 19.5 0 0 1 492.5 512 Z',
        fill: col.hand,
      }, this.hand);
      el('circle', { cx: C, cy: C, r: 6, fill: col.dot }, dial);

      // AM / PM switch
      const p = G.period;
      const period = el('g', { class: 'clock__period', tabindex: 0, role: 'switch', 'aria-label': 'PM' }, svg);
      el('rect', { class: 'clock__period-bg', x: p.x, y: p.y, width: p.w, height: p.h, rx: p.r, fill: col.periodBg }, period);
      this.thumb = el('rect', {
        class: 'clock__period-thumb', x: p.thumbX, y: p.thumbY, width: p.thumbW, height: p.thumbH, rx: p.thumbR, fill: col.periodThumb,
      }, period);
      const textAttrs = { y: p.y + p.h / 2 + 1, 'text-anchor': 'middle', 'dominant-baseline': 'central', 'font-size': 34, class: 'clock__num' };
      this.amText = el('text', { ...textAttrs, x: p.thumbX + p.thumbW / 2 }, period);
      this.amText.textContent = 'AM';
      this.pmText = el('text', { ...textAttrs, x: p.x + p.w - 4 - p.thumbW / 2 }, period);
      this.pmText.textContent = 'PM';

      this.dial = dial;
      this.period = period;
      this.root.replaceChildren(svg);
      this.svg = svg;
    }

    _render(animate) {
      const m12 = this.minutesOfDay % HALF;
      const target = m12 * 0.5;                               // 360° per 12 h
      const delta = mod(target - this.rotation + 180, 360) - 180; // shortest way round
      this.rotation += delta;

      this.hand.style.transition = animate ? '' : 'none';
      this.hand.style.transform = `rotate(${this.rotation}deg)`;

      const t = this.getTime();
      this.timeText.textContent = `${t.hours}:${String(t.minutes).padStart(2, '0')}`;

      const pm = t.period === 'PM';
      const shift = G.period.w - 8 - G.period.thumbW;        // thumb travel
      this.thumb.style.transform = pm ? `translateX(${shift}px)` : '';
      this.amText.setAttribute('fill', pm ? G.colors.periodOff : G.colors.periodOn);
      this.pmText.setAttribute('fill', pm ? G.colors.periodOn : G.colors.periodOff);

      this.dial.setAttribute('aria-valuenow', this.minutesOfDay);
      this.dial.setAttribute('aria-valuetext', t.label);
      this.period.setAttribute('aria-checked', String(pm));
      this.root.dataset.time = t.value;

      if (this.onChange) this.onChange(t);
    }

    /* ---------- interaction ---------- */

    _pointToMinutes(e) {
      const pt = this.svg.createSVGPoint();
      pt.x = e.clientX; pt.y = e.clientY;
      const p = pt.matrixTransform(this.svg.getScreenCTM().inverse());
      const deg = mod((Math.atan2(p.x - C, C - p.y) * 180) / Math.PI, 360);
      return mod(Math.round((deg * 2) / this.step) * this.step, HALF);   // 0..715
    }

    _setFromPointer(e, crossing) {
      const prev = this.minutesOfDay % HALF;
      const next = this._pointToMinutes(e);
      let isPM = this.minutesOfDay >= HALF;
      // Dragging across 12 flips AM/PM
      if (crossing && ((prev >= 540 && next < 180) || (prev < 180 && next >= 540))) isPM = !isPM;
      const value = next + (isPM ? HALF : 0);
      if (value === this.minutesOfDay) return;
      this.minutesOfDay = value;
      this._render(!crossing);
    }

    _bind() {
      const dial = this.dial;

      dial.addEventListener('pointerdown', (e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        dial.focus({ preventScroll: true });
        dial.setPointerCapture(e.pointerId);
        this.dragging = true;
        this.root.classList.add('is-dragging');
        this._setFromPointer(e, false);
      });
      dial.addEventListener('pointermove', (e) => {
        if (this.dragging) this._setFromPointer(e, true);
      });
      const end = () => {
        if (!this.dragging) return;
        this.dragging = false;
        this.root.classList.remove('is-dragging');
        this.commit();
      };
      dial.addEventListener('pointerup', end);
      dial.addEventListener('pointercancel', end);
      dial.addEventListener('lostpointercapture', end);

      dial.addEventListener('keydown', (e) => {
        const big = e.shiftKey ? 60 : this.step;
        const moves = {
          ArrowUp: big, ArrowRight: big, ArrowDown: -big, ArrowLeft: -big,
          PageUp: 60, PageDown: -60,
        };
        if (e.key === 'Home') {
          this.minutesOfDay = 0;
        } else if (e.key in moves) {
          this.minutesOfDay = mod(this.minutesOfDay + moves[e.key], DAY);
        } else if (e.key === 'Enter') {
          this.commit();
          return;
        } else {
          return;
        }
        e.preventDefault();
        this._render(true);
        clearTimeout(this.keyTimer);                 // commit after the user stops pressing
        this.keyTimer = setTimeout(() => this.commit(), 600);
      });
      dial.addEventListener('blur', () => {
        clearTimeout(this.keyTimer);
        this.commit();
      });

      const setPeriod = (pm) => {
        const isPM = this.minutesOfDay >= HALF;
        if (pm === isPM) return;
        this.minutesOfDay = mod(this.minutesOfDay + HALF, DAY);
        this._render(true);
        this.commit();
      };
      this.period.addEventListener('click', (e) => {
        const pt = this.svg.createSVGPoint();
        pt.x = e.clientX; pt.y = e.clientY;
        const x = pt.matrixTransform(this.svg.getScreenCTM().inverse()).x;
        if (e.detail === 0) setPeriod(this.minutesOfDay < HALF);           // keyboard-triggered click
        else setPeriod(x > G.period.x + G.period.w / 2);                   // clicked AM or PM half
      });
      this.period.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setPeriod(this.minutesOfDay < HALF); }
        if (e.key === 'ArrowLeft') { e.preventDefault(); setPeriod(false); }
        if (e.key === 'ArrowRight') { e.preventDefault(); setPeriod(true); }
      });
    }
  }

  global.ForecastClock = ForecastClock;
})(window);
