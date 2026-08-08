# Alamo Drafthouse Winchester — Marquee

What's playing at one theater: Alamo Drafthouse Winchester, VA. Poster grid,
showtimes, series/event tags, and a content-signal layer, on a phone.

Not a ticketing app. Not a multi-theater aggregator. No accounts, no login.

## Status

| Step | State |
|---|---|
| 1 — Endpoint discovery | **Blocked.** Egress policy denies `drafthouse.com`. Fetch layer written, field mapping deliberately not. |
| 2 — TMDB enrichment | **Written, never executed.** Same block (`api.themoviedb.org`). Follows TMDB's documented v3 contract. |
| 3 — Content severity parser | **Built and tested.** Needs no network. |
| 3b — Series/event treatments | **Built and tested.** Seed vocabulary, needs reconciling against the real feed. |
| 4 — Display | **Built and verified in Chromium.** Companion page + Scriptable widget. |
| 5 — Ops | **Built.** 6-hour cron, atomic cache, stale degradation, gap logging. |

Everything downstream of the feed is finished and verified against fixtures.
The one thing missing is `alamo.to_titles()` — the mapping from Alamo's field
names onto `marquee/model.py`. See [the blocker](#the-step-1-blocker).

> **Render target changed mid-build.** The brief specified wall furniture — a
> kiosk legible from across a room. The target is now a phone, which inverts
> the layout constraints. It also collides with one of the brief's
> non-negotiables: iOS and Android widgets have no in-widget interaction beyond
> a tap target, so the drill-in panel **cannot** live inside a home-screen
> widget. The resolution is a glanceable widget backed by a companion page that
> carries the full grid and the panels. Tapping the widget opens the page.

### The Step 1 blocker

This is not the 503-to-naive-clients problem described in the brief. Requests
never reach Alamo's edge at all. The sandbox routes outbound HTTPS through a
policy-enforcing egress proxy, and that proxy refuses the CONNECT tunnel:

```
$ curl https://drafthouse.com/winchester       # realistic UA + full browser headers
curl: (56) CONNECT tunnel failed, response 403

$ curl -sS "$HTTPS_PROXY/__agentproxy/status"
"recentRelayFailures": [{
  "kind": "connect_rejected",
  "detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)",
  "host": "drafthouse.com:443"
}]
```

Every host this project needs is denied — `drafthouse.com`, `www.drafthouse.com`,
`api.themoviedb.org`, `image.tmdb.org`, `www.filmratings.com`, `www.imdb.com`.
Only source-hosting domains resolve. The proxy documentation is explicit that
policy denials are to be reported rather than routed around, so no workaround
was attempted.

**Consequence:** the field inventory the brief asks for cannot be produced from
this environment. Discovery has to run from a host with normal outbound access,
or this sandbox's egress allowlist needs those domains added.

**What was built instead of guessing.** `marquee/adapters/alamo.py` has its
transport half written — browser-realistic headers, hydration-payload
extraction, candidate endpoints — and a `discover()` that dumps a
pretty-printed sample plus a field inventory, and reports which of the fields
the display needs were actually found. Its `to_titles()` raises
`DiscoveryPending` rather than inventing field names, because code that guesses
a schema looks finished and is confidently wrong.

Run this from a box with outbound access:

```
python3 -m marquee.adapters.alamo discover
```

`to_titles()` is the only function left to write. Severity, series resolution,
the build pipeline, the page and the widget are all written against
`marquee/model.py` and work unchanged the moment it returns real `Title`s.

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

40 tests: the intensity ladder, clause scoping, longest-match resolution,
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
marquee/adapters/alamo.py  fetch layer + discover(); field mapping NOT written

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
