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

## Structure

```
swift-landing/
├── index.html          landing: hero, ribbons, How it works, Open Data, Live Map, footer
├── map.html            full-screen map with Forecast Controls
├── server.py           local server
├── css/
│   ├── fonts.css       @font-face for NAMU, Buvera, Clash Display
│   ├── styles.css      tokens, layout, hover states, animations, responsive
│   └── map.css         map page styles
├── js/
│   ├── main.js         scroll reveal, endless ribbons, smooth scrolling
│   ├── clock.js        ForecastClock — interactive clock (SVG)
│   └── map.js          Weekday/Weekend switch, clock setup, onTimeSet()
└── assets/
    ├── img/            original images exported from Figma
    ├── icons/          original SVGs (arrow, social circle)
    └── fonts/          ClashDisplay-Bold.ttf
```

## Fonts

| Font in Figma | Where it's used | Status |
|---|---|---|
| NAMU 1960 | headings | **add the file** `assets/fonts/NAMU-1960.woff2` (or `.otf`) |
| NAMU Pro | body text | **add the file** `assets/fonts/NAMU-Pro.woff2` (or `.otf`) |
| Buvera Bold | SWIFT logo | **add the file** `assets/fonts/Buvera-Bold.woff2` (or `.otf`) |
| Clash Display Bold | "in an hour" | included |
| DM Sans Medium | menu, buttons | Google Fonts |
| FontAwesome 4.7 | icons | cdnjs |

Until the NAMU and Buvera files are added, the page uses Inter Tight / Inter / Clash Display.
If those fonts are installed on your system, they are picked up automatically.

## Interactions

- Menu: smooth scrolling to sections, animated underline on hover.
- Buttons: lift and shadow on hover; the arrow slides on hover.
- Ribbons "Built on open data…": endless scroll in opposite directions, pause on hover.
- Sections fade in on scroll; the iPhone floats gently.
- Cards and map: the image zooms slightly on hover.
- "Open the map" / "Open Full-Screen Map" / the map image open `map.html`.
- `map.html`: Weekday ⇄ Weekend (the active pill moves first, as in the two Figma frames).
- `prefers-reduced-motion` turns off all animations.

## Forecast clock (`map.html`)

The clock is drawn as SVG to the measurements of the Figma image (`assets/img/clock.png` is kept for reference only).

- Drag the hand or click on the dial: the time snaps in 5-minute steps. Dragging the hand past 12 switches AM ⇄ PM.
- AM / PM: click either half of the switch.
- Keyboard (focus the dial): ← → ↑ ↓ change the time by 5 minutes; Shift + arrow or PageUp / PageDown change it by 1 hour; Home sets 12:00 AM.

When the user **finishes** changing the time, the clock reports it. That happens when the hand is released, 0.6 s after the last key press, or when AM/PM is switched. If the time didn't change, nothing is reported.

```js
// js/map.js — called with the time the clock was set to
function onTimeSet(time) {
  // time = { hours: 3, minutes: 15, period: 'PM', hours24: 15, value: '15:15', label: '3:15 PM' }
  return time;
}

// Anywhere else:
SWIFT.getForecastTime();        // current time on the clock
SWIFT.setForecastTime(17, 30);  // set it from code (24-hour)
document.addEventListener('forecast:timeset', (e) => console.log(e.detail));
```
