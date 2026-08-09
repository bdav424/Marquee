// Winchester Marquee — Scriptable home-screen widget (iOS).
//
// Install: put this file in Scriptable's folder (Files > Scriptable), add a
// Scriptable widget to the home screen, and set its script to this one. Set
// MARQUEE_URL below to the box serving web/.
//
// The widget is the glance. It cannot host the drill-in panel — iOS widgets
// have no in-widget interaction beyond a tap target — so tapping anywhere
// opens the companion page, which carries the full grid and the "why".
//
// It renders the verdict the fetcher already computed and never decides
// anything itself, so the widget and the page can never disagree about
// whether a title is dimmed.
//
// An Android equivalent reads this identical JSON; nothing here is
// iOS-specific except the Scriptable API calls.

const MARQUEE_URL = 'http://winchester.local:8080';

const DATA_URL = `${MARQUEE_URL}/data/marquee.json`;
const PAGE_URL = `${MARQUEE_URL}/index.html`;
const CACHE_FILE = 'winchester-marquee.json';

const BG = new Color('#0B0B0E');
const TEXT = new Color('#F2F2F0');
const DIM_TEXT = new Color('#F2F2F0', 0.34); // the weighting, on a widget
const MUTED = new Color('#9A9AA6');
const ACCENT = new Color('#E8B33C');
const ALERT = new Color('#E5484D');

// ---------- data, with its own fallback cache ----------

function cachePath() {
  const fm = FileManager.local();
  return fm.joinPath(fm.cacheDirectory(), CACHE_FILE);
}

async function loadData() {
  try {
    const req = new Request(DATA_URL);
    req.timeoutInterval = 8;
    const data = await req.loadJSON();
    FileManager.local().writeString(cachePath(), JSON.stringify(data));
    return data;
  } catch (err) {
    // Box asleep or off the network: stale beats blank, same rule as the page.
    const fm = FileManager.local();
    if (fm.fileExists(cachePath())) {
      const cached = JSON.parse(fm.readString(cachePath()));
      cached.stale = true;
      return cached;
    }
    return null;
  }
}

// ---------- time helpers ----------

const dayKey = iso => iso.slice(0, 10);
const todayKey = () => {
  const d = new Date();
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
};

function timeLabel(iso) {
  const d = new Date(iso);
  let h = d.getHours();
  const m = d.getMinutes().toString().padStart(2, '0');
  const suffix = h >= 12 ? 'p' : 'a';
  h = h % 12 || 12;
  return m === '00' ? `${h}${suffix}` : `${h}:${m}${suffix}`;
}

function relativeAge(iso) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return `${Math.max(mins, 0)}m`;
  const hrs = Math.round(mins / 60);
  return hrs < 24 ? `${hrs}h` : `${Math.round(hrs / 24)}d`;
}

/* Upcoming showings, flattened across titles and sorted by time. Past
   showtimes are dropped — a widget showing this afternoon's 2pm at 9pm is
   worse than showing nothing. */
function upcoming(data, limit) {
  const now = Date.now();
  const rows = [];
  for (const t of data.titles) {
    for (const s of t.showings) {
      const when = new Date(s.showtime).getTime();
      if (when < now) continue;
      rows.push({ title: t, showing: s, when });
    }
  }
  rows.sort((a, b) => a.when - b.when);

  // One row per title — the soonest showing — so a four-show title cannot
  // crowd everything else off a small widget.
  const seen = new Set();
  const out = [];
  for (const row of rows) {
    if (seen.has(row.title.slug)) continue;
    seen.add(row.title.slug);
    out.push(row);
    if (out.length >= limit) break;
  }
  return out;
}

// ---------- rendering ----------

function header(w, data) {
  const row = w.addStack();
  row.centerAlignContent();

  const title = row.addText('WINCHESTER');
  title.font = Font.heavySystemFont(11);
  title.textColor = TEXT;

  row.addSpacer();

  const age = data.stale
    ? `stale ${relativeAge(data.fetched_at)}`
    : relativeAge(data.fetched_at);
  const stamp = row.addText(age);
  stamp.font = Font.mediumSystemFont(9);
  stamp.textColor = data.stale ? ACCENT : MUTED;

  w.addSpacer(7);
}

function showingRow(w, { title, showing }, compact) {
  const row = w.addStack();
  row.centerAlignContent();
  row.spacing = 6;

  // Series colour as a leading rule — one-night programming is why this
  // display exists, so it reads before the title does.
  const rule = row.addStack();
  rule.size = new Size(3, compact ? 13 : 15);
  rule.cornerRadius = 1.5;
  rule.backgroundColor = title.series
    ? new Color(title.series.background)
    : new Color('#2C2C36');

  const dimmed = title.flagged;

  const time = row.addText(timeLabel(showing.showtime));
  time.font = Font.semiboldSystemFont(compact ? 10 : 11);
  time.textColor = dimmed ? DIM_TEXT : TEXT;
  time.lineLimit = 1;

  const name = row.addText(title.display_name || title.name);
  name.font = Font.systemFont(compact ? 10 : 11);
  name.textColor = dimmed ? DIM_TEXT : TEXT;
  name.lineLimit = 1;

  row.addSpacer();

  // Unknown is surfaced, never silently treated as clean.
  if (!title.reason_parsed) {
    const q = row.addText('?');
    q.font = Font.boldSystemFont(compact ? 9 : 10);
    q.textColor = ACCENT;
  } else if (dimmed) {
    const dot = row.addText('•');
    dot.font = Font.boldSystemFont(compact ? 11 : 12);
    dot.textColor = new Color(ALERT.hex, 0.75);
  }

  w.addSpacer(compact ? 3 : 4);
}

function footer(w, data, shownCount) {
  const total = data.titles.length;
  if (total <= shownCount) return;
  w.addSpacer(1);
  const more = w.addText(`+${total - shownCount} more`);
  more.font = Font.systemFont(9);
  more.textColor = MUTED;
}

async function build() {
  const w = new ListWidget();
  w.backgroundColor = BG;
  w.setPadding(12, 13, 12, 13);
  w.url = PAGE_URL; // tap -> the page that can actually explain itself

  const data = await loadData();

  if (!data) {
    const t = w.addText('Winchester');
    t.font = Font.heavySystemFont(12);
    t.textColor = TEXT;
    w.addSpacer(4);
    const e = w.addText('No cache yet — is the box reachable?');
    e.font = Font.systemFont(10);
    e.textColor = MUTED;
    return w;
  }

  const family = config.widgetFamily || 'medium';
  const compact = family === 'small';
  const limit = family === 'small' ? 3 : family === 'large' ? 9 : 5;

  header(w, data);

  const rows = upcoming(data, limit);
  if (rows.length === 0) {
    const none = w.addText('Nothing left today.');
    none.font = Font.systemFont(11);
    none.textColor = MUTED;
  } else {
    for (const row of rows) showingRow(w, row, compact);
    footer(w, data, rows.length);
  }

  w.addSpacer();
  return w;
}

const widget = await build();
if (config.runsInWidget) {
  Script.setWidget(widget);
} else {
  await widget.presentMedium();
}
Script.complete();
