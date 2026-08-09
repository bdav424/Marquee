# Alamo Drafthouse Winchester — Marquee

What's playing at one theater: Alamo Drafthouse Winchester, VA. Poster grid,
showtimes, series/event tags, and a content-signal layer, on a phone.

Not a ticketing app. Not a multi-theater aggregator. No accounts, no login.

## Status

| Step | State |
|---|---|
| 1 — Endpoint discovery | **Done.** JSON API found and mapped. |
| 2 — TMDB enrichment | **Running.** Runtime, genres, synopsis, cached posters. |
| 3 — Content severity parser | **Built, tested and fed.** Input is a hand-kept book — see below. |
| 3b — Series/event treatments | **Built and tested.** Reconciling against the real feed. |
| 4 — Display | **Built and verified in Chromium.** Poster grid, split-flap board, widgets, 4 themes. |
| 5 — Ops | **Built.** 6-hour cron, atomic cache, stale degradation, gap logging. |

The pipeline runs end to end against real Winchester data. 191 tests.

Latest cycle on the box: 32 titles fetched, 32 posters cached, 0 TMDB
failures, 2 dimmed. 26 titles are waiting on a rating reason and show `?`.

Thresholds are per-viewer and set in the browser, so the config file is only
the default. See [Your thresholds](#your-thresholds-not-the-configs).

### The feed

`drafthouse.com` is an Angular SPA — the served HTML is a 4.5 KB shell with no
schedule in it, so scraping the page is a dead end. The schedule is a JSON API:

```
GET https://drafthouse.com/s/mother/v2/schedule/market/winchester
    -> ~630 KB, {"data": {presentations, sessions, formats, agePolicies, ...}}
```

The join is `sessions[].presentationSlug` → `presentations[].slug`. Sessions
carry time, screen, format and admission policy; presentations carry the film.
Sibling endpoints harvested from Alamo's JS bundles are in `KNOWN_ENDPOINTS`.

Two useful things it gives us for free: **Alamo publishes its own poster art**,
so TMDB is only needed for runtime, genres and synopsis; and every session
carries `cinemaTimeZoneName`, so showtimes are correct even if the box serving
the display sits in another timezone.

### The problem: no rating reasons anywhere

**Alamo does not publish MPA rating-reason strings.** It publishes the
certification (`R`, `PG-13`) and nothing more. A scan of all 630 KB for
reason-shaped text found only `agePolicies[].name` — admission policies like
`"Rated PG with Adult Focus"`, not `"Rated R for strong bloody violence"`.

TMDB does not carry reason strings either; its maintainers declined to model
them. So the input the entire content-signal layer was designed around does
not currently exist, and **every title scores `unknown` and nothing greys.**

The parser is fine. It has nothing to eat.

This is why `unknown` was built as a state distinct from clean. A display that
defaulted missing reasons to "no content issues" would show a wall of
confidently unflagged titles and quietly mean nothing. Instead it shows `?`
and says so.

**The fix is `config/reasons.toml`, kept by hand.** Every automatic source is
closed:

| Source | Certification | Reason text |
|---|---|---|
| Alamo feed | yes | no |
| TMDB | yes | no — not modelled |
| OMDb | yes | no |
| Wikidata | yes | no property for it |
| IMDb free non-commercial datasets | no | no |
| IMDb paid bulk data (AWS Data Exchange) | yes | yes, licensed per use case |
| filmratings.com (CARA) | yes | yes — **behind bot protection** |

CARA is the MPA's own database and the origin of every one of these sentences,
so `marquee/adapters/filmratings.py` was written against it. It cannot be
queried. Probing the live site showed no query parameter is honoured — eight
candidate names all return the same page, and `filmTitle`, which the adapter
originally used, was never one of the page's real fields. A POST returns the
unfiltered page byte-for-byte, the page contains no `<form>` at all, and its
scripts load `_Incapsula_Resource`: the site sits behind Imperva bot
protection. Reaching the search would mean defeating an access control, which
this project will not do. The adapter stays, switchable via
`MARQUEE_TRY_CARA=1`, in case that ever changes.

So the reasons are typed in, which is less work than it sounds. One theatre
runs about ten films at a time, a reason never changes once CARA assigns it,
and each cycle writes `logs/needs-reason.txt` with a ready-to-paste stub for
anything still missing. Copy the sentence verbatim — the parser reads the
wording, so `strong bloody violence` and `some violence` score differently.

Two things keep that queue short. **Pre-1990 films are dropped from it
automatically**: CARA only began issuing descriptors in 1990, so a revival
screening of a 1976 film has no sentence to find and asking for one is asking
for work that cannot be done. TMDB supplies the release year on a call the
enricher already makes, so this costs nothing. And **the stub is ordered
newest first**, because a first-run release is what somebody is deciding about
tonight, while a question mark on a repertory booking is a fine answer.

The panel says which kind of question mark it is looking at. "No rating reason
was published" is a gap somebody can close; "released 1976, before the MPA
began issuing rating descriptors" is permanent, and saying so is more useful
than a bare `?`.

Titles match loosely: case, punctuation, leading articles, a trailing year and
Alamo's programming prefixes are all ignored, so `Terror Tuesday: The Thing`
finds an entry filed under `The Thing`.

A title with no entry stays `unknown` and shows a question mark. That is the
honest state, and it is why `unknown` exists as something distinct from clean:
a display that defaulted missing reasons to "no content issues" would show a
wall of confidently unflagged titles and quietly mean nothing.

### Your thresholds, not the config's

`config/marquee.toml` sets what the fetcher computes, but the verdict it bakes
into the snapshot is one person's judgement, and the person holding the phone
may not agree. The gear icon opens a settings sheet that re-derives `flagged`
in the browser from the same per-category severity scores the payload already
carries — per-category thresholds from Never to Severe, the Horror backstop,
whether unreadable ratings should count, and dim-versus-hide.

Both surfaces read the same preferences, so a title dimmed on the grid is
dimmed on the board. Nothing is sent anywhere; it lives in localStorage on
that device.

Two rules survive the customisation, because they are what make the signal
worth trusting:

- **Unknown never satisfies a threshold.** A title whose reason could not be
  read has `null` severities, and null is not a low score. Flagging unknown is
  an explicit opt-in, off by default.
- **Hiding announces itself.** `hide` mode does remove titles from the list —
  the original brief said never hide anything, and this is a deliberate
  departure — but the count stays on screen with a one-tap "Show them". A
  filter you cannot see is indistinguishable from a film that is not playing,
  and that is the failure mode the whole content signal exists to avoid.

## What is built: the severity parser

`marquee/severity.py` turns an MPA rating-reason string into a per-category
severity vector, then applies flagging thresholds. It is pure and offline —
string in, verdict out — so it was buildable despite the blocker, and it is the
piece most specific to this project.

```
"Rated R for strong bloody violence, language throughout, and some sexual content."

  sexual      1     -> FLAG (threshold 1)
  violence    3     -> FLAG (threshold 3)
  language    3        chip only, never flags
  substance   0
  frightening 0
```

### Design notes

- **All vocabulary and thresholds live in `config/marquee.toml`.** Nothing is
  hardcoded. Keyword sets, the intensity ladder, per-category thresholds, and
  the genre backstop are all tunable without touching Python.
- **Unknown is not zero.** A missing string, or one that yields no recognisable
  category, scores `unknown` across the board — never silently "clean". Unknown
  never flags on its own, and the UI is expected to surface it as unknown.
- **Longest-match, consuming keyword resolution.** `disturbing images` resolves
  to `violence` and does not also trip `disturbing` under `frightening`.
- **Dual-role terms count twice, deliberately.** `bloody` is both a violence
  keyword and a level-3 modifier, so `bloody violence` scores 3 rather than
  falling back to the bare-noun default of 2. Modifier scanning runs against
  the raw fragment, independent of keyword consumption.
- **Modifiers are clause-scoped.** In `strong bloody violence, language
  throughout, and some sexual content`, `strong` does not leak onto `sexual`.
  Within a comma-segment, a conjunction fragment with no modifier of its own
  inherits the segment's leading one, so `some violence and gore` scores both
  at 1. Toggle via `inherit_modifiers_across_conjunction`.
- **Unmatched fragments are captured**, not discarded — `SeverityVector.unmatched`
  is the backlog for extending the keyword sets, per Step 5's logging requirement.
- **Provenance is preserved.** Every flag carries its category, score, threshold,
  and the verbatim fragments that produced it, plus the untouched original
  string. That is exactly what the drill-in panel needs.

### Vocabulary beyond the brief

`config/marquee.toml` has a `[categories_extra]` table holding real MPA phrasings
the starting keyword sets miss — `violent content`, `grisly images`, `peril`,
`drug references`, and similar. They merge into the main sets at load time and
are kept in a separate table so they are easy to audit or delete outright.

### Thresholds as configured

| Category | Rule |
|---|---|
| `sexual` | `>= 1` — flags, including "brief" |
| `violence` | `>= 3` — moderate is fine, sadistic/grisly is not |
| `frightening` | `>= 2`, **or** TMDB genre includes Horror |
| `language` | never flags — chip displays, carries no weight |
| `substance` | never flags |

## What is built: series/event treatments

`marquee/series.py` resolves whatever series string the feed carries to a
visual treatment — per-series colour, label, and a `one_night` flag, distinct
from the rating chip.

- **Nothing is dropped.** An unrecognised strand still badges, using the
  default treatment and its own verbatim label, and is reported via
  `unrecognised()` for reconciliation. Silently discarding an unknown strand
  would hide exactly the one-night programming this display exists to surface.
- **Matching is text-based, not schema-based.** It resolves off a normalised
  form of the tag string, so it works without knowing the feed's field shape.
- **Whole-word matching.** Patterns match on token boundaries, so `rep` cannot
  match inside `prepare`. This was a live bug caught in review, now guarded by
  a test.
- **Priority ordering.** A showing carrying several tags gets the
  highest-priority one as its primary badge; the rest are retained as
  secondary.

`config/series.toml` is **seed data** — Alamo's well-known strands from the
brief plus public programming names. It has not been reconciled against the
real Winchester feed, because discovery is blocked.

## What is built: the display

Two surfaces, one cache, one verdict.

**Companion page** (`web/`) — phone-first poster grid, no framework, no build
step. It reads the cached snapshot and never touches the network at render.
The content-signal rules are honoured literally:

- Every title playing is **always rendered**. Nothing is ever filtered out.
- A title tripping a threshold is **desaturated and pushed back**, not removed,
  and stays tappable.
- Tapping any title opens a panel naming the category, the score, the threshold
  it crossed, and the **verbatim** rating string it was derived from.
- The rating chip shows on every card regardless of verdict.
- Unknown severity shows a `?` and is described as unknown — not clean.

**Split-flap board** (`web/board.html`) — a Solari marquee. Every character is
a real flap: hinged at the midline, the lit face falls forward covering the
outgoing letter while the incoming letter's lower half swings down behind it.
Rolling from A toward Z means stepping the drum one flip at a time.

- Flap size is **measured, not guessed** — cells are sized from the row's
  actual width, so the time column cannot be pushed off a narrow screen.
- **It is a sign, not a page.** A bounded marquee board with a bezel and
  chasing border lamps, hanging on a dark theatre wall that catches its spill
  light. The lit face runs to the end of the content, not the bottom of the
  viewport — a lit rectangle filling the screen read as a blank page.
- **The whole face is lit**, not just the tiles. The panel behind the flaps
  glows too; the only black left is the letters and the physical seams. Tiles
  separate from the face by cast shadow and edge, not by sitting on darkness.
- **Dimming keeps the board lit.** Turning flagged flaps down read as a broken
  bulb; instead the face stays fully lit and the letters fade toward the flap
  colour, holding ~3.8:1 contrast so a weighted row still reads.
- The next showing is always the next one **not yet started**, so once the
  day's last screening has gone the row rolls onto tomorrow by itself.
- A data change re-rolls only what actually changed; an in-flight roll is
  superseded rather than queued, so the board never chases a stale target.
- Tapping a row deep-links to the grid's drill-in panel — the board is the
  glance, the panel is where a verdict explains itself.
- `prefers-reduced-motion` snaps straight to the final characters.

**Android widget** (`android/`) — a home-screen widget in Kotlin, reading the
same snapshot. Six rows, dimmed titles fading toward the flap colour, `?` for
unknown, tap opens the board. No chasing lamps or split-flap animation: a
widget repaints on the host's schedule, not per frame. **Never compiled** —
written without an Android SDK to hand, so treat it as reviewed, not working.
See [android/README.md](android/README.md).

**iOS widget** (`widget/marquee-widget.js`) — Scriptable, iOS. The glance: next
showings, series colour as a leading rule, dimmed titles at reduced alpha, `?`
for unknown. Tapping opens the companion page. An Android equivalent reads the
identical JSON.

Neither surface computes a verdict — `marquee/build.py` does, once — so the two
cannot disagree about whether a title is dimmed.

Verified in Chromium at 390×844: 7 cards render, 3 dimmed, drill-in opens, no
JS errors, stale banner surfaces correctly.

## What is built: ops

- **6-hour cron** (`scripts/refresh.py`). Alamo posts about a week out; polling
  harder buys nothing.
- **Atomic writes** — the snapshot is written to a temp file and renamed, so
  the display can never read a half-written file.
- **Stale beats blank.** A failed cycle retains the last good snapshot,
  re-emits it with `stale: true`, and the header shows its age. Verified: with
  the adapter blocked, the page renders the full grid under a
  "Stale — last successful fetch 4 min ago" banner.
- **Gap logging** (`logs/parse-failures.jsonl`) — every reason-string fragment
  the vocabulary missed, every string it could not read, and every unconfigured
  series tag. That is the list to extend the config from.
- **Posters cached to disk**, never hotlinked, with a generated fallback tile
  when art is missing.

Deployment, including the systemd unit and the crontab line, is in
[docs/deploy.md](docs/deploy.md).

## Running the tests

No dependencies. Python 3.11+ for stdlib `tomllib`.

```
python3 -m unittest discover -s tests -t .
```

191 tests: the intensity ladder, clause scoping, longest-match resolution,
unknown handling, thresholds and provenance for the severity parser; strand
recognition, match precedence, whole-word guarding and unrecognised-tag
retention for series treatments; the payload contract, chronological ordering
across a DST change and atomic writing for the snapshot builder; field mapping,
offset derivation and decoration stripping for the Alamo adapter.

## Serving the page

`web/data/marquee.json` is generated, not committed — a fresh clone has no
snapshot until you make one:

```
python3 scripts/refresh.py          # real schedule, needs network
python3 scripts/build_sample.py     # invented fixtures, works offline
cd web && python3 -m http.server 8080
```

Then `http://<box>:8080/board.html` for the split-flap sign, `index.html` for
the poster grid.

## Layout

```
config/marquee.toml        tunable vocabulary, ladder, thresholds
config/series.toml         series/event tag treatments (seed data)
config/reasons.toml        MPA rating reasons, kept by hand

marquee/model.py           the normalised contract everything is written against
marquee/severity.py        rating-reason parser + threshold evaluation
marquee/series.py          series tag resolution + visual treatment
marquee/reasons.py         the hand-kept reason book
marquee/build.py           combines them into the display snapshot
marquee/tmdb.py            enrichment + poster caching (written, never executed)
marquee/adapters/alamo.py  JSON schedule API + discover() + field mapping
marquee/images.py          poster caching, never hotlinked

web/                       companion page (phone-first, no framework)
widget/marquee-widget.js   Scriptable home-screen widget (iOS)
android/                   home-screen widget (Android, built in CI)

scripts/refresh.py         cron entry point — fetch, build, degrade gracefully
scripts/build_sample.py    display JSON from invented fixtures, not real data

tests/test_severity.py     regression surface — add mis-read strings here first
tests/test_series.py       regression surface — add mis-resolved tags here first
```

## Decisions taken

- **Phone replaces the wall display** entirely. No across-the-room legibility
  constraint.
- **Widget + companion page**, since a widget alone cannot satisfy the
  drill-in requirement.
- **Scriptable** for the widget — a real home-screen widget that installs
  without Xcode or an App Store build. iOS only; an Android equivalent reads
  the same JSON. This one was a judgement call, not confirmed.
- **Series tags get their own strong treatment**, per-strand colour, distinct
  from the rating chip, with one-night programming marked and sorted first.
- Python fetcher, plain HTML/CSS/JS display, no framework. Nothing here
  justified one.

## Still open

- Egress for `drafthouse.com` and TMDB, without which Step 1 cannot run.
- Whether Scriptable is the right widget mechanism, or whether this should be
  an Android or native build.
- `config/series.toml` is seed data and has never been checked against
  Winchester's actual programming.

## Non-goals

Ticket purchasing. Multiple theaters. User accounts. Anything requiring an
Alamo login.
