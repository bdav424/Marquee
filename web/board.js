/* Split-flap marquee board.
 *
 * Each character is a physical flap: hinged at the midline, the lit face
 * falls forward covering the outgoing letter while the incoming letter's
 * lower half swings down behind it. Rolling from A toward Z means stepping
 * through the character set one flip at a time, exactly like the real thing.
 *
 * Reads the same cached snapshot as the poster grid and renders the same
 * verdict, so the two surfaces can never disagree.
 */

'use strict';

const DATA_URL = 'data/marquee.json';
const POLL_MS = 60000;

// The physical drum. Order matters — a flap rolls forward through this list
// and wraps, so the sequence is what you see counting past.
const DRUM = ' ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:.,\'&!?-/+';
const DRUM_INDEX = new Map([...DRUM].map((c, i) => [c, i]));

// One full 180deg turn. At 62ms the fold was over before the eye caught it;
// the Solari references sit around 150ms and 100 keeps a long roll bearable.
const FLIP_MS = 100;
const COL_STAGGER = 18;    // each column starts slightly after the one left of it
const ROW_STAGGER = 70;

const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

let snapshot = null;
let lastSignature = null;

/* ---------- one flap cell ---------- */

class Cell {
  constructor() {
    this.current = ' ';
    this.queue = null;
    this.running = false;

    this.el = document.createElement('div');
    this.el.className = 'cell';
    this.el.innerHTML =
      '<div class="half top"><div class="ink"></div></div>' +
      '<div class="half bottom"><div class="ink"></div></div>' +
      '<div class="flip">' +
        '<div class="side front"><div class="ink"></div><div class="shade"></div></div>' +
        '<div class="side back"><div class="ink"></div><div class="shade"></div></div>' +
      '</div>';

    this.flipEl = this.el.querySelector('.flip');
    this.topInk = this.el.querySelector('.half.top .ink');
    this.bottomInk = this.el.querySelector('.half.bottom .ink');
    this.frontInk = this.el.querySelector('.side.front .ink');
    this.backInk = this.el.querySelector('.side.back .ink');
    this.frontShade = this.el.querySelector('.side.front .shade');
    this.backShade = this.el.querySelector('.side.back .shade');
    this.paint(' ');
  }

  paint(ch) {
    this.topInk.textContent = ch;
    this.bottomInk.textContent = ch;
    this.current = ch;
  }

  /* Roll forward through the drum until the target shows. */
  async roll(target, delay = 0) {
    const ch = DRUM_INDEX.has(target) ? target : ' ';
    if (ch === this.current) return;

    if (reduceMotion) { this.paint(ch); return; }

    // A newer render supersedes an in-flight roll rather than queueing behind
    // it, so a data update never leaves the board chasing a stale target.
    this.queue = ch;
    if (this.running) return;
    this.running = true;

    if (delay) await sleep(delay);

    let guard = DRUM.length + 1;
    while (this.queue !== this.current && guard-- > 0) {
      const next = DRUM[(DRUM_INDEX.get(this.current) + 1) % DRUM.length];
      await this.flip(next);
    }
    this.running = false;
  }

  /* One card, hinged at the midline, turning a continuous 180deg: it starts
     covering the top half showing the outgoing glyph and lands covering the
     bottom half showing the incoming one. The static halves underneath are
     set so the top is already the new glyph (revealed as the card leaves) and
     the bottom is still the old one (hidden as the card arrives). */
  async flip(next) {
    this.frontInk.textContent = this.current;
    this.backInk.textContent = next;
    this.topInk.textContent = next;

    this.el.classList.add('flipping');

    const running = [
      this.flipEl.animate(
        [{ transform: 'rotateX(0deg)' }, { transform: 'rotateX(-180deg)' }],
        { duration: FLIP_MS, easing: 'cubic-bezier(0.36, 0.06, 0.42, 1)' }),

      // Shadow ramps across the fold. Without it the rotation is nearly
      // invisible against a flat lit face and reads as a text swap.
      this.frontShade.animate(
        [{ opacity: 0 }, { opacity: 0.9 }],
        { duration: FLIP_MS / 2, easing: 'ease-in', fill: 'forwards' }),

      this.backShade.animate(
        [{ opacity: 1, offset: 0 }, { opacity: 1, offset: 0.5 }, { opacity: 0, offset: 1 }],
        { duration: FLIP_MS, easing: 'linear', fill: 'forwards' }),
    ];

    await Promise.all(running.map(a => a.finished.catch(() => {})));

    this.el.classList.remove('flipping');
    // Filled animations accumulate on the element otherwise — one per flip,
    // forever, on every cell.
    for (const animation of running) animation.cancel();
    this.paint(next);
  }
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ---------- a run of cells ---------- */

class Split {
  constructor(length, extraClass, align = 'left') {
    this.align = align;
    this.el = document.createElement('div');
    this.el.className = 'split' + (extraClass ? ' ' + extraClass : '');
    this.cells = Array.from({ length }, () => new Cell());
    for (const cell of this.cells) this.el.appendChild(cell.el);
  }

  set(text, rowIndex = 0) {
    const width = this.cells.length;
    let body = (text || '').toUpperCase().slice(0, width);

    // A short title left-aligned in a long flap run left a tail of blank
    // cards, which is not how a board reads. Titles are centred over their
    // run; times are right-aligned so the digits line up column to column.
    if (this.align === 'center') {
      body = ' '.repeat(Math.floor((width - body.length) / 2)) + body;
    } else if (this.align === 'right') {
      body = body.padStart(width, ' ');
    }

    const padded = body.padEnd(width, ' ');
    this.cells.forEach((cell, i) => {
      cell.roll(padded[i], rowIndex * ROW_STAGGER + i * COL_STAGGER);
    });
  }
}

/* ---------- schedule logic ---------- */

const dayKey = iso => iso.slice(0, 10);

function localDayKey(offset = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-` +
         `${String(d.getDate()).padStart(2, '0')}`;
}

function dayLabel(iso) {
  // Abbreviated: "TOMORROW" cost a whole title flap to spell out.
  if (dayKey(iso) === localDayKey(0)) return 'TODAY';
  if (dayKey(iso) === localDayKey(1)) return 'TMRW';
  return new Date(iso).toLocaleDateString(undefined, { weekday: 'short' }).toUpperCase();
}

function timeLabel(iso) {
  const d = new Date(iso);
  let h = d.getHours();
  const m = String(d.getMinutes()).padStart(2, '0');
  const suffix = h >= 12 ? 'P' : 'A';
  h = h % 12 || 12;
  return `${h}:${m}${suffix}`;
}

/* The next showing that has not already started. Once the day's last show has
   gone, this rolls onto tomorrow by itself — the board never advertises a
   screening you have already missed. */
function nextShowing(title) {
  const now = Date.now();
  for (const showing of title.showings) {
    if (new Date(showing.showtime).getTime() >= now) return showing;
  }
  return null;
}

function rows(data) {
  return data.titles
    .map(title => ({ title, showing: nextShowing(title) }))
    .filter(entry => entry.showing)
    .sort((a, b) => new Date(a.showing.showtime) - new Date(b.showing.showtime));
}

/* ---------- border lamps ---------- */

/* A mechanical marquee chaser, modelled on the real thing.
 *
 * The original was a motor turning a drum with contacts that struck each
 * circuit in turn. Bulbs are not wired individually — they are split into a
 * few CHANNELS, and bulb n belongs to channel n % channels, so every third
 * lamp shares a wire. The drum energises the channels in rotation and the lit
 * set appears to travel.
 *
 * Channel count is the whole trick. Two channels cannot show direction: with
 * every other lamp lit, bulb n and bulb n+2 are identical and the eye has no
 * way to tell which way the pattern is moving, so it reads as flashing rather
 * than rotating. Three is the documented minimum for a stable sense of
 * motion, which is why the previous alternation never looked circular.
 */
const BULB_CHANNELS = 3;      // circuits on the drum
const BULB_ON_CHANNELS = 2;   // how many are energised at once
const BULB_PERIOD_MS = 1100;  // one full revolution of the drum
const BULB_SPACING = 11;
const BULB_INSET = 11;

/* Keyframes are generated so the lit fraction always matches the channel
   wiring above rather than being restated as a percentage by hand. */
function installChaseKeyframes() {
  const duty = (BULB_ON_CHANNELS / BULB_CHANNELS) * 100;
  const style = document.getElementById('chase-keyframes')
    || Object.assign(document.createElement('style'), { id: 'chase-keyframes' });
  style.textContent = `@keyframes commutator {
    0%, ${duty.toFixed(3)}% {
      opacity: 1;
      box-shadow: 0 0 5px 1px rgba(255, 201, 110, 0.85);
    }
    ${(duty + 0.001).toFixed(3)}%, 100% {
      opacity: 0.34;
      box-shadow: none;
    }
  }`;
  if (!style.isConnected) document.head.appendChild(style);
}

/* A point at arc-length `d` around the sign's perimeter, clockwise from the
   top-left corner. */
function perimeterPoint(d, w, h) {
  if (d < w) return [BULB_INSET + d, BULB_INSET];
  d -= w;
  if (d < h) return [BULB_INSET + w, BULB_INSET + d];
  d -= h;
  if (d < w) return [BULB_INSET + w - d, BULB_INSET + h];
  d -= w;
  return [BULB_INSET, BULB_INSET + h - d];
}

function buildBulbs() {
  const sign = document.querySelector('.sign');
  const holder = document.getElementById('bulbs');
  if (!sign || !holder) return;

  const rect = sign.getBoundingClientRect();
  const w = rect.width - BULB_INSET * 2;
  const h = rect.height - BULB_INSET * 2;
  if (w <= 0 || h <= 0) return;

  installChaseKeyframes();

  // Lamps are placed by arc length rather than per edge, so spacing is
  // identical the whole way round instead of differing between the long and
  // short sides. The count is forced to a multiple of the channel count so
  // the wiring pattern meets itself cleanly where the loop closes.
  const perimeter = 2 * (w + h);
  const count =
    Math.max(BULB_CHANNELS,
      Math.round(perimeter / BULB_SPACING / BULB_CHANNELS) * BULB_CHANNELS);
  const step = perimeter / count;

  holder.replaceChildren(...Array.from({ length: count }, (_, i) => {
    const [x, y] = perimeterPoint(i * step, w, h);
    const bulb = document.createElement('div');
    bulb.className = 'bulb';
    bulb.style.left = `${x.toFixed(1)}px`;
    bulb.style.top = `${y.toFixed(1)}px`;
    if (!reduceMotion) {
      const channel = i % BULB_CHANNELS;
      bulb.style.animationDuration = `${BULB_PERIOD_MS}ms`;
      // Each channel fires a third of a revolution after the one before it.
      // The channel index is reversed so the pattern travels the same way the
      // lamps are numbered — clockwise from the top-left. Using the channel
      // directly ran the chase backwards around the sign.
      const lag = (BULB_CHANNELS - channel) % BULB_CHANNELS;
      bulb.style.animationDelay =
        `${-(lag * BULB_PERIOD_MS) / BULB_CHANNELS}ms`;
    }
    return bulb;
  }));
}

/* ---------- board ---------- */

const TIME_CELLS = 6;
const CELL_GAP = parseFloat(
  getComputedStyle(document.documentElement).getPropertyValue('--cell-gap')
) || 2;
// A tall card gets its legibility from height, so the width floor can come
// back down and the titles get their characters back.
const MIN_CELL_W = 12;
const META_W = 40;

/* Cell size is measured, not guessed. A fixed cell width overflowed the row
   on a 390px phone and pushed the time column off the right edge, so the
   board now fits itself to the space it actually has. */
function layout() {
  const container = document.getElementById('rows');
  const avail = container.clientWidth - 4 /* strip */ - 20 /* row gaps */ - META_W;

  // Take as many title flaps as fit without dropping below a legible cell.
  let titleCells = 18;
  const width = () =>
    Math.floor((avail - (titleCells + TIME_CELLS) * CELL_GAP) /
               (titleCells + TIME_CELLS));

  while (width() < MIN_CELL_W && titleCells > 7) titleCells--;

  const cellW = Math.max(width(), MIN_CELL_W);
  // Read each time rather than cached at load, so the aspect can be changed
  // at runtime and the board relaid without a reload.
  const aspect = parseFloat(
    getComputedStyle(document.documentElement).getPropertyValue('--cell-aspect')
  ) || 2;
  const root = document.documentElement.style;
  root.setProperty('--cell-w', `${cellW}px`);
  root.setProperty('--cell-h', `${Math.round(cellW * aspect)}px`);
  return titleCells;
}

let titleCells = 0;
const built = new Map();

function buildRow(entry) {
  const row = document.createElement('div');
  row.className = 'row';

  const strip = document.createElement('div');
  strip.className = 'strip';
  row.appendChild(strip);

  const name = new Split(titleCells, null, 'center');
  row.appendChild(name.el);

  const time = new Split(TIME_CELLS, 'times', 'right');
  row.appendChild(time.el);

  const meta = document.createElement('div');
  meta.className = 'meta';
  row.appendChild(meta);

  row.addEventListener('click', () => {
    // The board is the glance; the grid is where a verdict explains itself.
    location.href = `index.html#${entry.title.slug}`;
  });

  return { row, strip, name, time, meta };
}

function render(data) {
  const grid = document.getElementById('rows');
  const entries = rows(data);

  // A width change alters how many flaps fit, so the rows are rebuilt.
  const width = layout();
  if (width !== titleCells) {
    titleCells = width;
    for (const parts of built.values()) parts.row.remove();
    built.clear();
  }

  document.getElementById('empty').hidden = entries.length > 0;

  entries.forEach((entry, index) => {
    const key = entry.title.slug;
    let parts = built.get(key);
    if (!parts) {
      parts = buildRow(entry);
      built.set(key, parts);
    }
    grid.appendChild(parts.row);   // re-append reorders in place

    parts.row.classList.toggle('flagged', !!entry.title.flagged);
    parts.strip.style.background = entry.title.series
      ? entry.title.series.background
      : 'rgba(244,228,188,0.16)';

    parts.name.set(entry.title.name, index);
    parts.time.set(timeLabel(entry.showing.showtime), index);

    // Two lines, not four — a 34px row has no space for a stack.
    const second = [entry.title.rating || 'NR'];
    if (!entry.title.reason_parsed) second.push('<span class="unknown">?</span>');
    if (entry.showing.sold_out) second.push('<span class="soldout">SOLD</span>');
    parts.meta.innerHTML =
      `<span class="day">${dayLabel(entry.showing.showtime)}</span>` +
      `<span class="tags">${second.join(' ')}</span>`;
  });

  // Drop rows for titles no longer playing.
  for (const [key, parts] of built) {
    if (!entries.some(e => e.title.slug === key)) {
      parts.row.remove();
      built.delete(key);
    }
  }

  // The sign's perimeter changes with its content, so the lamps are relaid
  // after the rows settle rather than once at startup.
  requestAnimationFrame(buildBulbs);
}

function renderStamp(data) {
  const node = document.getElementById('stamp');
  const mins = Math.round((Date.now() - new Date(data.fetched_at).getTime()) / 60000);
  const age = mins < 60 ? `${Math.max(mins, 0)}M` : `${Math.round(mins / 60)}H`;
  node.textContent = data.stale ? `STALE · ${age}` : `UPDATED ${age} AGO`;
  node.classList.toggle('stale', !!data.stale);
}

async function load() {
  const res = await fetch(DATA_URL, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function tick(force) {
  let data;
  try {
    data = await load();
  } catch (err) {
    document.getElementById('stamp').textContent = 'NO SIGNAL';
    document.getElementById('stamp').classList.add('stale');
    return;
  }

  // Only re-roll when something actually changed, or when a showtime has
  // lapsed and the next one should take its place.
  const signature = JSON.stringify(
    rows(data).map(e => [e.title.slug, e.showing.showtime, e.title.flagged])
  );
  snapshot = data;
  renderStamp(data);
  if (!force && signature === lastSignature) return;
  lastSignature = signature;
  render(data);
}

tick(true);
setInterval(() => tick(false), POLL_MS);

let resizeTimer;
addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (snapshot) render(snapshot);
    else buildBulbs();
  }, 200);
});
