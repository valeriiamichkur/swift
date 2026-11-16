# SWIFT — landing page

Code for the Figma file **apps → page "bikes"**:

| Page | Figma frame |
|---|---|
| `index.html` | `citi bikes` (135:59), 1440 × 4066 |
| `map.html` | `maps` (135:145 Weekday / 135:171 Weekend), 1420 × 960 |

## Run

```bash
python3 server.py --open
```

Opens http://localhost:8000. Use `--port 5050` to pick another port. The server only uses the Python standard library.

Run it from this folder **inside the project repo**: it reads `../forecast.py`, `../data/data.json`
(build it with `python data/analyze_data.py`) and keeps the live-feed backup in `../fallback_feed.csv`,
the same files the Streamlit app uses. Opening the HTML files directly (`file://`) shows the pages,
but the maps need the server.

## Live station map

Both `map.html` (full screen) and the "Live Station Map" block on `index.html` are interactive
Leaflet maps of New York (`js/station-map.js`, `css/station-map.css`; Leaflet from cdnjs, Esri
dark-gray tiles, no API key). Every Citi Bike station is a dot coloured like the Streamlit map:

| Colour | Status | Meaning |
|---|---|---|
| vermillion | `low` | expected bikes ≤ threshold → likely to run out of bikes |
| blue | `high` | expected free docks ≤ threshold → likely to overflow |
| off-white | `medium` | fine |

From zoom 15 the stations in view turn into numbered pins (expected bikes), as in the Figma map.
Hover a dot for its name, click it for bikes now, capacity, net flow and the expected count.

On `map.html` the markers follow the **Forecast Controls**: the clock time and Weekday/Weekend pick
the 1-hour window, and the map re-forecasts when you release the hand, switch AM/PM or switch the
day type. On load both are set to the current New York time and day, so the first view matches the
Streamlit app. The landing preview always shows the next hour from now. Both refresh every minute.

### `GET /api/forecast`

| Param | Default | |
|---|---|---|
| `day` | today's type in New York | `weekday` or `weekend` |
| `time` | now in New York | `HH:MM`, 24-hour; start of the 1-hour window |
| `threshold` | `forecast.DEFAULT_THRESHOLD` (2) | bikes / free docks, clamped to `THRESHOLD_RANGE` |

Expected bikes = live bike count now + average net flow for `time` → `time + 1 h` on a `day`
(the date used is the next one of that type, so a window that crosses midnight into the weekend
uses weekend flows for that part). The math is `forecast.predict_station_availability`. The live
GBFS snapshot is cached for 60 s; if the feed is down the backup CSV is used and the response says
`"is_backup": true`.

```json
{ "day": "weekday", "time": "17:00",
  "window": { "start": "2026-11-16T17:00:00-05:00", "end": "2026-11-16T18:00:00-05:00" },
  "as_of": "2026-11-16T12:31:57-05:00", "is_backup": false, "threshold": 2.0,
  "counts": { "low": 587, "high": 154, "medium": 1728, "no_history": 177, "skipped": 0 },
  "history": { "first_day": "2026-09-01", "last_day": "2026-09-13", "days": { "weekday": 8, "weekend": 4 } },
  "stations": [ { "id": "…", "name": "Walker St & Baxter St", "lat": 40.717411, "lon": -73.999573,
                  "capacity": 47, "bikes": 45, "docks": 1, "expected": 42.6, "bounded": 42.6,
                  "net_flow": -2.38, "status": "medium", "no_history": false } ] }
```

## Structure

```
swift-landing/
├── index.html          landing: hero, ribbons, How it works, Open Data, Live Map, footer
├── map.html            full-screen map with Forecast Controls
├── server.py           local server + /api/forecast
├── css/
│   ├── fonts.css       @font-face for NAMU, Buvera, Clash Display
│   ├── styles.css      tokens, layout, hover states, animations, responsive
│   ├── map.css         map page styles
│   └── station-map.css Leaflet map: markers, pins, legend, popups
├── js/
│   ├── main.js         scroll reveal, endless ribbons, smooth scrolling
│   ├── clock.js        ForecastClock — interactive clock (SVG)
│   ├── map.js          Weekday/Weekend switch, clock setup, onTimeSet() → map
│   └── station-map.js  SwiftStationMap — Leaflet map fed by /api/forecast
└── assets/
    ├── img/            original images exported from Figma
    ├── icons/          original SVGs (arrow, social circle)
    └── fonts/          ClashDisplay-Bold.ttf
```

## Fonts

| Font in Figma | Where it's used | File in `assets/fonts/` |
|---|---|---|
| NAMU 1960 | headings | `NAMU-1960.woff2` (+ `.woff`, `.ttf` fallbacks) |
| NAMU Pro | body text | `NAMU-Pro.woff2` (+ `.woff`, `.otf` fallbacks) |
| Buvera Bold | SWIFT logo | `Buvera-Bold.otf` |
| Clash Display Bold | "in an hour" | `ClashDisplay-Bold.ttf` |
| DM Sans Medium | menu, buttons | Google Fonts |
| FontAwesome 4.7 | icons | cdnjs |

`css/fonts.css` loads only these bundled files (no `local()`), so the page looks the same on every
machine whether or not the fonts are installed. Serve the page with `server.py`: some browsers
refuse web fonts on `file://` pages.

## Interactions

- Menu: smooth scrolling to sections, animated underline on hover.
- Buttons: lift and shadow on hover; the arrow slides on hover.
- Ribbons "Built on open data…": endless scroll in opposite directions, pause on hover.
- Sections fade in on scroll; the iPhone floats gently.
- Cards: the image zooms slightly on hover.
- "Open the map" / "Open Full-Screen Map" open `map.html`; the Live Station Map block is a live, draggable map.
- `map.html`: Weekday ⇄ Weekend (the active pill moves first, as in the two Figma frames).
- `prefers-reduced-motion` turns off all animations.

## Forecast clock (`map.html`)

The clock is drawn as SVG to the measurements of the Figma image (`assets/img/clock.png` is kept for reference only).

- Drag the hand or click on the dial: the time snaps in 5-minute steps. Dragging the hand past 12 switches AM ⇄ PM.
- AM / PM: click either half of the switch.
- Keyboard (focus the dial): ← → ↑ ↓ change the time by 5 minutes; Shift + arrow or PageUp / PageDown change it by 1 hour; Home sets 12:00 AM.

When the user **finishes** changing the time, the clock reports it. That happens when the hand is released, 0.6 s after the last key press, or when AM/PM is switched. If the time didn't change, nothing is reported.

```js
// js/map.js — called with the time the clock was set to; reloads the map
function onTimeSet(time) {
  // time = { hours: 3, minutes: 15, period: 'PM', hours24: 15, value: '15:15', label: '3:15 PM' }
  refresh();   // → /api/forecast?day=<weekday|weekend>&time=15:15
  return time;
}

// Anywhere else:
SWIFT.getForecastTime();        // current time on the clock
SWIFT.setForecastTime(17, 30);  // set it from code (24-hour) and reload the map
SWIFT.stationMap.data;          // last /api/forecast response
document.addEventListener('forecast:timeset', (e) => console.log(e.detail));
```
