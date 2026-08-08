/* Winchester marquee — companion page.
 *
 * Reads the cached snapshot and renders it. Never touches the network beyond
 * that one local file, and never computes a verdict itself: the fetcher
 * already decided, so this page and the widget cannot disagree.
 *
 * The rule this file exists to honour: every title is always shown. Flagged
 * titles are dimmed and remain tappable. Nothing is filtered out, ever.
 */

'use strict';

const DATA_URL = 'data/marquee.json';
const MAX_TIMES_ON_CARD = 6;

let snapshot = null;

/* ---------- helpers ---------- */

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

const dayKey = iso => iso.slice(0, 10);

function dayLabel(iso) {
  const d = new Date(iso);
  const today = new Date();
  const t = dayKey(today.toISOString());
  const tomorrow = new Date(today.getTime() + 86400000);
  if (dayKey(iso) === t) return 'Today';
  if (dayKey(iso) === dayKey(tomorrow.toISOString())) return 'Tomorrow';
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

function timeLabel(iso) {
  return new Date(iso)
    .toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
    .replace(/\s?([AP])M/i, (_, p) => p.toLowerCase());
}

function isToday(iso) {
  return dayKey(iso) === dayKey(new Date().toISOString());
}

function relativeAge(iso) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 2) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

/* Deterministic hue so a missing poster still gets a stable identity
   rather than a grey hole or a broken image. */
function hue(slug) {
  let h = 0;
  for (let i = 0; i < slug.length; i++) h = (h * 31 + slug.charCodeAt(i)) % 360;
  return h;
}

/* ---------- cards ---------- */

function posterNode(title) {
  if (title.poster) {
    const img = el('img', 'poster');
    img.src = title.poster;
    img.alt = '';
    img.loading = 'lazy';
    // Cached art can go missing; fall back rather than showing a broken image.
    img.onerror = () => img.replaceWith(posterFallback(title));
    return img;
  }
  return posterFallback(title);
}

function posterFallback(title) {
  const n = el('div', 'poster poster-fallback', title.name.charAt(0).toUpperCase());
  const h = hue(title.slug);
  n.style.background = `linear-gradient(160deg, hsl(${h} 24% 20%), hsl(${(h + 40) % 360} 20% 12%))`;
  return n;
}

/* One-night programming is the perishable half of the schedule, so the marker
   is a deliberate second line rather than a suffix that wraps at card width. */
function seriesBadge(series) {
  const b = el('div', 'series-badge');
  b.style.background = series.background;
  b.style.color = series.foreground;
  b.appendChild(el('span', 'strand', series.label));
  if (series.one_night) b.appendChild(el('span', 'one-night-tag', 'One night only'));
  return b;
}

function makeCard(title) {
  const card = el('button', 'card' + (title.flagged ? ' flagged' : ''));
  card.type = 'button';

  const unknown = !title.reason_parsed;
  const bits = [title.name];
  if (title.rating) bits.push(`rated ${title.rating}`);
  if (title.flagged) bits.push('dimmed, tap for why');
  if (unknown) bits.push('rating reason unknown');
  card.setAttribute('aria-label', bits.join(', '));

  const shell = el('div', 'poster-shell');
  shell.style.position = 'relative';
  shell.appendChild(posterNode(title));

  if (title.series) shell.appendChild(seriesBadge(title.series));

  const badges = el('div', 'badge-row');
  // Rating chip shows on every card regardless of verdict.
  badges.appendChild(el('span', 'chip', title.rating || 'NR'));
  if (unknown) badges.appendChild(el('span', 'chip chip-unknown', '?'));
  if (title.flagged) {
    const cats = title.flags.map(f => f.category === 'genre' ? 'horror' : f.category);
    badges.appendChild(el('span', 'chip chip-flag', cats.join(' · ')));
  }
  shell.appendChild(badges);
  card.appendChild(shell);

  const body = el('div', 'card-body');
  body.appendChild(el('h2', 'card-title', title.name));
  body.appendChild(timesNode(title.showings, MAX_TIMES_ON_CARD));
  card.appendChild(body);

  card.addEventListener('click', () => openSheet(title));
  return card;
}

function timesNode(showings, limit) {
  const wrap = el('div', 'times');
  let lastDay = null;
  let shown = 0;

  for (const s of showings) {
    if (limit && shown >= limit) {
      wrap.appendChild(el('span', 'time', `+${showings.length - shown}`));
      break;
    }
    const key = dayKey(s.showtime);
    if (key !== lastDay) {
      wrap.appendChild(el('span', 'daylabel', dayLabel(s.showtime)));
      lastDay = key;
    }
    let cls = 'time';
    if (isToday(s.showtime)) cls += ' today';
    if (s.sold_out) cls += ' sold-out';
    const node = el('span', cls, timeLabel(s.showtime));
    if (s.format) node.title = s.format + (s.auditorium ? ` · ${s.auditorium}` : '');
    wrap.appendChild(node);
    shown++;
  }
  return wrap;
}

/* ---------- drill-in sheet ---------- */

function severityRow(cat, score, threshold) {
  const row = el('div', 'sev-row');
  row.appendChild(el('div', 'sev-name', cat));

  const track = el('div', 'sev-track');
  const tripped = threshold != null && score != null && score >= threshold;
  for (let i = 1; i <= 3; i++) {
    const seg = el('div', 'sev-seg');
    if (score != null && score >= i) seg.className += tripped ? ' on tripped' : ' on';
    track.appendChild(seg);
  }
  row.appendChild(track);

  let label, cls;
  if (score == null) { label = 'unknown'; cls = 'sev-val unknown'; }
  else if (threshold == null) { label = ['none', 'mild', 'moderate', 'severe'][score] + ' *'; cls = 'sev-val muted'; }
  else if (tripped) { label = `${score} ≥ ${threshold}`; cls = 'sev-val tripped'; }
  else { label = ['none', 'mild', 'moderate', 'severe'][score]; cls = 'sev-val'; }
  row.appendChild(el('div', cls, label));
  return row;
}

function openSheet(title) {
  const body = document.getElementById('sheet-body');
  body.replaceChildren();

  const h = el('h2', null, title.name);
  h.id = 'sheet-title';
  body.appendChild(h);

  const meta = [title.rating || 'NR'];
  if (title.runtime_minutes) meta.push(`${title.runtime_minutes} min`);
  if (title.genres && title.genres.length) meta.push(title.genres.join(', '));
  body.appendChild(el('p', 'sheet-meta', meta.join('  ·  ')));

  if (title.series) {
    const b = seriesBadge(title.series);
    b.style.position = 'static';
    b.style.borderRadius = '8px';
    b.style.marginBottom = '14px';
    body.appendChild(b);
    if (!title.series.recognised) {
      body.appendChild(el('p', 'sheet-meta',
        'Unrecognised series — badged from the feed text, not yet configured.'));
    }
  }

  /* The verdict, and its working. */
  const unknown = !title.reason_parsed;
  const v = el('div', 'verdict ' +
    (title.flagged ? 'verdict-flagged' : unknown ? 'verdict-unknown' : 'verdict-clear'));

  if (title.flagged) {
    v.appendChild(el('h3', null, 'Dimmed because'));
    const ul = el('ul');
    for (const f of title.flags) {
      const li = el('li');
      if (f.category === 'genre') {
        li.textContent = f.reason;
      } else {
        const words = ['none', 'mild', 'moderate', 'severe'];
        li.textContent = `${f.category} — ${words[f.score]} (${f.score}), your threshold is ${f.threshold}`;
        if (f.evidence && f.evidence.length) {
          li.appendChild(el('div', 'sheet-meta', `from “${f.evidence.join('; ')}”`));
        }
      }
      ul.appendChild(li);
    }
    v.appendChild(ul);
  } else if (unknown) {
    v.appendChild(el('h3', null, 'Not rated by this display'));
    v.appendChild(el('p', null, title.rating_reason
      ? 'The rating reason could not be parsed, so severity is unknown — not known to be clean. Shown at full weight rather than guessed at.'
      : 'No rating reason was published for this title, so severity is unknown — not known to be clean.'));
  } else {
    v.appendChild(el('h3', null, 'Under all your thresholds'));
    v.appendChild(el('p', null, 'Nothing here trips a rule you set.'));
  }
  body.appendChild(v);

  /* Verbatim source text — the thing the verdict was derived from. */
  body.appendChild(el('h4', null, 'MPA rating reason, verbatim'));
  if (title.rating_reason) {
    body.appendChild(el('blockquote', 'reason-quote', title.rating_reason));
  } else {
    body.appendChild(el('blockquote', 'reason-quote absent', 'No rating reason published.'));
  }

  body.appendChild(el('h4', null, 'Severity'));
  const thresholds = snapshot.thresholds || {};
  const cats = snapshot.categories || Object.keys(title.severity);
  let showsNeverFlagMark = false;
  for (const cat of cats) {
    const score = title.severity[cat];
    const threshold = thresholds[cat] ?? null;
    if (threshold == null && score != null) showsNeverFlagMark = true;
    body.appendChild(severityRow(cat, score, threshold));
  }
  // Only footnote the marker when a row actually carries it.
  if (showsNeverFlagMark) {
    const note = el('p', 'sheet-meta', '* never flags — shown for information only');
    note.style.marginTop = '8px';
    body.appendChild(note);
  }

  body.appendChild(el('h4', null, 'Showtimes'));
  const times = timesNode(title.showings, 0);
  times.className = 'times sheet-times';
  body.appendChild(times);

  if (title.synopsis) {
    body.appendChild(el('h4', null, 'Synopsis'));
    body.appendChild(el('p', 'synopsis', title.synopsis));
  }

  document.getElementById('sheet').hidden = false;
  document.getElementById('sheet-backdrop').hidden = false;
  document.body.style.overflow = 'hidden';
  document.getElementById('sheet-close').focus();
}

function closeSheet() {
  document.getElementById('sheet').hidden = true;
  document.getElementById('sheet-backdrop').hidden = true;
  document.body.style.overflow = '';
}

/* ---------- boot ---------- */

function renderFreshness(data) {
  const node = document.getElementById('freshness');
  const age = relativeAge(data.fetched_at);
  const flagged = data.diagnostics ? data.diagnostics.flagged_count : 0;
  const parts = [`${data.titles.length} playing`];
  if (flagged) parts.push(`${flagged} dimmed`);
  // Stale cache with a visible timestamp beats a blank screen.
  node.textContent = data.stale
    ? `Stale — last successful fetch ${age} · ${parts.join(' · ')}`
    : `Updated ${age} · ${parts.join(' · ')}`;
  node.classList.toggle('stale', !!data.stale);
}

async function boot() {
  const grid = document.getElementById('grid');
  try {
    const res = await fetch(DATA_URL, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    snapshot = await res.json();
  } catch (err) {
    document.getElementById('freshness').textContent = 'Cache unreadable — ' + err.message;
    document.getElementById('freshness').classList.add('stale');
    grid.removeAttribute('aria-busy');
    return;
  }

  renderFreshness(snapshot);
  grid.replaceChildren(...snapshot.titles.map(makeCard));
  grid.removeAttribute('aria-busy');
  document.getElementById('empty').hidden = snapshot.titles.length > 0;
}

document.getElementById('sheet-close').addEventListener('click', closeSheet);
document.getElementById('sheet-backdrop').addEventListener('click', closeSheet);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSheet(); });

const legendBtn = document.getElementById('legend-toggle');
legendBtn.addEventListener('click', () => {
  const legend = document.getElementById('legend');
  legend.hidden = !legend.hidden;
  legendBtn.setAttribute('aria-expanded', String(!legend.hidden));
});

boot();
