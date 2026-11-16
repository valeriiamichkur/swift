/* SwiftStationMap — interactive New York map with Citi Bike forecast markers.
   Needs Leaflet (loaded from cdnjs in the HTML) and the /api/forecast endpoint
   served by server.py.

   const map = new SwiftStationMap(element, { interactive: true });
   map.load({ day: 'weekday', time: '17:30' }).then((data) => ...);

   Markers use the same three statuses as the Streamlit app:
     low    → likely to run out of bikes   (vermillion)
     high   → likely to overflow           (blue)
     medium → fine                          (off-white)
   Zoomed out every station is a dot; from zoom 15 the stations in view become
   numbered pins showing the expected bike count, as in the Figma map. */
(function (global) {
  'use strict';

  const NYC_CENTER = [40.733, -73.975];
  const NYC_BOUNDS = [[40.45, -74.35], [41.0, -73.6]];
  // Esri dark-gray canvas: free, no API key. Base + a separate labels layer on top.
  const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/';
  const TILES = ESRI + 'World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}';
  const LABELS = ESRI + 'World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}';
  const ATTRIBUTION = 'Tiles &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors · <a href="https://citibikenyc.com/system-data">Citi Bike</a>';

  const STATUS = {
    low:    { label: 'Likely to empty',    fill: '#d55e00', stroke: '#ffb38a' },
    high:   { label: 'Likely to overflow', fill: '#1f6fd6', stroke: '#9cc4ff' },
    medium: { label: 'Fine',               fill: '#f4f2ee', stroke: '#1f1f1f' },
  };

  const LABEL_ZOOM = 15;   // from this zoom on, show numbered pins
  const MAX_LABELS = 400;  // safety cap on DOM pins in view

  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const timeFmt = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' });
  const formatTime = (iso) => (iso ? timeFmt.format(new Date(iso)) : '—');

  function signed(n) {
    const r = Math.round(n * 10) / 10;
    return (r > 0 ? '+' : r < 0 ? '−' : '±') + Math.abs(r);
  }

  function dotRadius(zoom, status) {
    const base = zoom <= 11 ? 2.2 : zoom === 12 ? 3 : zoom === 13 ? 4.5 : 6.5;
    return status === 'medium' ? base * 0.8 : base;
  }

  class SwiftStationMap {
    /**
     * @param {HTMLElement} el
     * @param {{interactive?: boolean, legend?: boolean, status?: boolean, zoom?: number}} [options]
     */
    constructor(el, options = {}) {
      const interactive = options.interactive !== false;
      this.el = el;
      this.data = null;
      this.markers = new Map();   // station id → L.circleMarker (dots, always drawn)
      this.pinById = new Map();   // station id → L.marker (numbered pins, zoom ≥ 15, in view)
      this.request = null;

      this.map = L.map(el, {
        preferCanvas: true,
        zoomControl: interactive,
        scrollWheelZoom: interactive,
        minZoom: 10,
        maxZoom: 18,
        maxBounds: L.latLngBounds(NYC_BOUNDS).pad(0.25),
        maxBoundsViscosity: 0.8,
      }).setView(NYC_CENTER, options.zoom || 13);

      L.tileLayer(TILES, { attribution: ATTRIBUTION, maxNativeZoom: 16, maxZoom: 18 }).addTo(this.map);
      this.map.createPane('labels').style.zIndex = 350;   // above tiles, below the station dots
      this.map.getPane('labels').style.pointerEvents = 'none';
      L.tileLayer(LABELS, { pane: 'labels', maxNativeZoom: 16, maxZoom: 18 }).addTo(this.map);

      this.renderer = L.canvas({ padding: 0.3 });
      this.dots = L.layerGroup().addTo(this.map);
      this.pins = L.layerGroup().addTo(this.map);

      if (options.legend !== false) this._addLegend();
      if (options.status !== false) this._addStatus();

      this.map.on('zoomend moveend', () => this._refreshView());
    }

    /**
     * Fetch the forecast for a day type and clock time and redraw the markers.
     * Earlier requests still in flight are cancelled.
     * @param {{day?: 'weekday'|'weekend', time?: string, threshold?: number}} params
     * @returns {Promise<object|null>} the API response, or null if superseded
     */
    async load(params = {}) {
      if (this.request) this.request.abort();
      const controller = new AbortController();
      this.request = controller;

      const query = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v != null) query.set(k, v);

      this._setStatus('loading', 'Updating forecast…');
      try {
        const res = await fetch(`/api/forecast?${query}`, { signal: controller.signal });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        this._render(data);
        this._setStatus(data.is_backup ? 'warn' : 'ok',
          data.is_backup ? `Live feed down · backup from ${formatTime(data.as_of)}` : `Live · stations as of ${formatTime(data.as_of)}`);
        return data;
      } catch (err) {
        if (err.name === 'AbortError') return null;
        console.error('[SWIFT] forecast failed:', err);
        this._setStatus('error', location.protocol === 'file:'
          ? 'Run python3 server.py to load stations'
          : `Could not load stations (${err.message})`);
        throw err;
      } finally {
        if (this.request === controller) this.request = null;
      }
    }

    /* ---------- drawing ---------- */

    _render(data) {
      this.data = data;
      const seen = new Set();
      const zoom = this.map.getZoom();

      for (const s of data.stations) {
        seen.add(s.id);
        const style = this._dotStyle(s, zoom);
        let marker = this.markers.get(s.id);
        if (!marker) {
          marker = L.circleMarker([s.lat, s.lon], { renderer: this.renderer, ...style });
          marker.bindPopup(() => this._popup(marker.station), { className: 'station-popup', maxWidth: 280 });
          marker.bindTooltip('', { direction: 'top', offset: [0, -4], className: 'station-tip' });
          this.markers.set(s.id, marker);
          this.dots.addLayer(marker);
        } else {
          marker.setStyle(style);
        }
        marker.station = s;
        marker.setTooltipContent(escapeHtml(s.name));
        if (marker.isPopupOpen()) marker.setPopupContent(this._popup(s));
      }
      for (const [id, marker] of this.markers) {
        if (!seen.has(id)) { this.dots.removeLayer(marker); this.markers.delete(id); }
      }
      this._refreshView();
    }

    _dotStyle(s, zoom) {
      const st = STATUS[s.status] || STATUS.medium;
      return {
        radius: dotRadius(zoom, s.status),
        color: st.stroke,
        weight: zoom >= 13 ? 1 : 0.5,
        fillColor: st.fill,
        fillOpacity: s.status === 'medium' ? 0.55 : 0.95,
        opacity: s.status === 'medium' ? 0.35 : 0.9,
      };
    }

    _refreshView() {
      if (!this.data) return;
      const zoom = this.map.getZoom();
      for (const marker of this.markers.values()) marker.setRadius(dotRadius(zoom, marker.station.status));

      const labelled = zoom >= LABEL_ZOOM;
      this.el.classList.toggle('is-labelled', labelled);
      if (!labelled) {
        this.pins.clearLayers();
        this.pinById.clear();
        return;
      }

      // Pins are diffed, not rebuilt: a popup auto-pan fires moveend, and
      // rebuilding would remove the pin that owns the open popup.
      const bounds = this.map.getBounds().pad(0.1);
      const wanted = new Set();
      for (const s of this.data.stations) {
        if (!bounds.contains([s.lat, s.lon])) continue;
        if (wanted.size >= MAX_LABELS) break;
        wanted.add(s.id);
        const value = Math.round(s.bounded);
        const key = `${s.status}|${value}`;
        let pin = this.pinById.get(s.id);
        if (!pin) {
          pin = L.marker([s.lat, s.lon], { title: s.name, riseOnHover: true, keyboard: true });
          pin.bindPopup(() => this._popup(pin.station), { className: 'station-popup', maxWidth: 280 });
          this.pinById.set(s.id, pin);
          this.pins.addLayer(pin);
        }
        pin.station = s;
        if (pin.key !== key) {
          pin.key = key;
          pin.setIcon(L.divIcon({
            className: '',
            html: `<span class="station-pin station-pin--${s.status}${value > 99 ? ' is-wide' : ''}">${value}</span>`,
            iconSize: [36, 36],
            iconAnchor: [18, 18],
            popupAnchor: [0, -16],
          }));
        }
        if (pin.isPopupOpen()) pin.setPopupContent(this._popup(s));
      }
      for (const [id, pin] of this.pinById) {
        if (wanted.has(id) || pin.isPopupOpen()) continue;
        this.pins.removeLayer(pin);
        this.pinById.delete(id);
      }
    }

    _popup(s) {
      const st = STATUS[s.status] || STATUS.medium;
      const w = this.data.window;
      const exp = Math.round(s.bounded * 10) / 10;
      return `
        <div class="sp">
          <p class="sp__name">${escapeHtml(s.name)}</p>
          <p class="sp__status sp__status--${s.status}"><i></i>${st.label}</p>
          <dl class="sp__grid">
            <dt>Now</dt><dd>${s.bikes} bikes · ${s.docks} docks free</dd>
            <dt>Capacity</dt><dd>${s.capacity}</dd>
            <dt>Net flow</dt><dd>${signed(s.net_flow)} bikes, ${formatTime(w.start)}–${formatTime(w.end)}</dd>
            <dt>Expected</dt><dd><b>${exp}</b> bikes at ${formatTime(w.end)}</dd>
          </dl>
          ${s.no_history ? '<p class="sp__note">No trip history for this station, so flow is assumed to be 0.</p>' : ''}
        </div>`;
    }

    /* ---------- overlays ---------- */

    _addLegend() {
      const legend = L.control({ position: 'bottomleft' });
      legend.onAdd = () => {
        const div = L.DomUtil.create('div', 'map-legend');
        div.innerHTML = ['low', 'high', 'medium']
          .map((k) => `<span class="map-legend__item"><i class="map-legend__dot map-legend__dot--${k}"></i>${STATUS[k].label}</span>`)
          .join('');
        return div;
      };
      legend.addTo(this.map);
    }

    _addStatus() {
      const status = L.control({ position: 'topright' });
      status.onAdd = () => {
        this.statusEl = L.DomUtil.create('div', 'map-status');
        this.statusEl.setAttribute('role', 'status');
        return this.statusEl;
      };
      status.addTo(this.map);
    }

    _setStatus(kind, text) {
      if (!this.statusEl) return;
      this.statusEl.className = `map-status map-status--${kind}`;
      this.statusEl.textContent = text;
    }
  }

  SwiftStationMap.formatTime = formatTime;
  global.SwiftStationMap = SwiftStationMap;
})(window);
