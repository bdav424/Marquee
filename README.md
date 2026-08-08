# Alamo Drafthouse Winchester — Marquee

An always-on wall display for one theater: Alamo Drafthouse Winchester, VA.
Poster wall, showtimes, series/event tags, and a content-signal layer.

Not a ticketing app. Not a multi-theater aggregator. No accounts, no login.

## Status

| Step | State |
|---|---|
| 1 — Endpoint discovery | **Blocked.** Network egress policy denies `drafthouse.com`. See below. |
| 2 — TMDB enrichment | **Blocked.** Same reason (`api.themoviedb.org`, `image.tmdb.org`). |
| 3 — Content severity parser | **Built and tested.** Needs no network. |
| 3b — Series/event treatments | **Built and tested.** Seed vocabulary, needs reconciling against the real feed. |
| 4 — Display | Not started — waiting on the field inventory and on the widget/companion split. |
| 5 — Ops (cron, cache, logging) | Not started — shape depends on Step 1. |

> **Render target changed.** The brief specified wall furniture — a kiosk display
> legible from across a room. The target is now a **phone widget**, which inverts
> most of the layout constraints (small, close, glanceable) and constrains the
> drill-in panel, since home-screen widgets do not host interactive panels. The
> content-signal rules are unaffected; the layout work in Step 4 is not yet
> started pending that decision.

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

## Running the tests

No dependencies. Python 3.11+ for stdlib `tomllib`.

```
python3 -m unittest discover -s tests -t .
```

39 tests: the intensity ladder, clause scoping, longest-match resolution,
unknown handling, thresholds and provenance for the severity parser; strand
recognition, match precedence, whole-word guarding and unrecognised-tag
retention for series treatments.

## Layout

```
config/marquee.toml     tunable vocabulary, ladder, thresholds
config/series.toml      series/event tag treatments (seed data)
marquee/severity.py     rating-reason parser + threshold evaluation
marquee/series.py       series tag resolution + visual treatment
tests/test_severity.py  regression surface — add mis-read strings here first
tests/test_series.py    regression surface — add mis-resolved tags here first
```

## Open questions before Step 4

- **Widget flavour.** A home-screen widget cannot host the clickable drill-in
  panel the brief calls non-negotiable, so the likely shape is a glanceable
  widget backed by a companion page that carries the full grid and the panels.
  Which widget mechanism — Scriptable, a home-screen PWA, or a native build —
  is unresolved.
- **Does the wall display still exist**, or has the phone replaced it entirely?
- Stack confirmation: Python fetcher + plain HTML/CSS/JS display, no framework.

## Non-goals

Ticket purchasing. Multiple theaters. User accounts. Anything requiring an
Alamo login.
