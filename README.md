# Alamo Drafthouse Winchester — Marquee

What's playing at one theater: Alamo Drafthouse Winchester, VA. Poster grid,
showtimes, series/event tags, and a content-signal layer, on a phone.

Not a ticketing app. Not a multi-theater aggregator. No accounts, no login.

## Status

| Step | State |
|---|---|
| 1 — Endpoint discovery | **Done.** JSON API found and mapped. |
| 2 — TMDB enrichment | **Wired, never executed.** Runtime, genres, synopsis. |
| 3 — Content severity parser | **Built and tested.** Has no input yet — see below. |
| 3b — Series/event treatments | **Built and tested.** Reconciling against the real feed. |
| 4 — Display | **Built and verified in Chromium.** Companion page + widget. |
| 5 — Ops | **Built.** 6-hour cron, atomic cache, stale degradation, gap logging. |

The pipeline runs end to end against real Winchester data. 64 tests.

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

**The fix is a `filmratings.com` adapter** — the official CARA database, which
publishes the exact strings the parser was written for. Not yet built. Until
it is, the only working content signal is the TMDB Horror genre backstop.

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

**Widget** (`widget/marquee-widget.js`) — Scriptable, iOS. The glance: next
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

64 tests: the intensity ladder, clause scoping, longest-match resolution,
unknown handling, thresholds and provenance for the severity parser; strand
recognition, match precedence, whole-word guarding and unrecognised-tag
retention for series treatments.

## Layout

```
config/marquee.toml        tunable vocabulary, ladder, thresholds
config/series.toml         series/event tag treatments (seed data)

marquee/model.py           the normalised contract everything is written against
marquee/severity.py        rating-reason parser + threshold evaluation
marquee/series.py          series tag resolution + visual treatment
marquee/build.py           combines them into the display snapshot
marquee/tmdb.py            enrichment + poster caching (written, never executed)
marquee/adapters/alamo.py  JSON schedule API + discover() + field mapping
marquee/images.py          poster caching, never hotlinked

web/                       companion page (phone-first, no framework)
widget/marquee-widget.js   Scriptable home-screen widget (iOS)

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
