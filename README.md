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
| 4 — Display | Not started — waiting on the real field inventory + hardware target. |
| 5 — Ops (cron, cache, logging) | Not started — shape depends on Step 1. |

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

## Running the tests

No dependencies. Python 3.11+ for stdlib `tomllib`.

```
python3 -m unittest discover -s tests -t .
```

25 tests covering the intensity ladder, clause scoping, longest-match
resolution, unknown handling, thresholds, and provenance.

## Layout

```
config/marquee.toml     tunable vocabulary, ladder, thresholds
marquee/severity.py     parser + threshold evaluation
tests/test_severity.py  regression surface — add mis-read strings here first
```

## Open questions before Step 4

- Screen size and hardware target (wall tablet? Pi + monitor? what resolution?)
- Should the series/event tag get its own visual treatment, distinct from the
  rating chip?
- Stack confirmation: Python fetcher + plain HTML/CSS/JS display, no framework.

## Non-goals

Ticket purchasing. Multiple theaters. User accounts. Anything requiring an
Alamo login.
