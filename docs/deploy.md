# Deploying the marquee

Target: a small always-on box on the LAN (a Pi is plenty) serving `web/` over
HTTP, with a cron job refreshing the cache every six hours. The phone talks to
that box; nothing is exposed to the internet and nothing needs an account.

## 1. Put it on the box

```
git clone <this repo> /opt/marquee
cd /opt/marquee
python3 --version        # needs 3.11+ for stdlib tomllib
python3 -m unittest discover -s tests -t .
```

No dependencies to install. That is deliberate — the fetcher uses `urllib`,
config is `tomllib`, and the display is plain HTML/CSS/JS. Nothing to keep
patched, nothing to break on a Pi rebuild.

## 2. TMDB key

Get a free v3 API key from themoviedb.org and put it in the environment the
cron job runs under:

```
# /etc/default/marquee
TMDB_API_KEY=your_key_here
```

The key is only ever read by `marquee/tmdb.py`. It is not needed to serve the
display, only to refresh it.

## 3. Serve `web/`

Any static server. The display reads one local JSON file and never touches the
network at render, so this does not need to be fast.

```
# /etc/systemd/system/marquee-web.service
[Unit]
Description=Winchester marquee display
After=network.target

[Service]
WorkingDirectory=/opt/marquee/web
ExecStart=/usr/bin/python3 -m http.server 8080 --bind 0.0.0.0
Restart=always
User=marquee

[Install]
WantedBy=multi-user.target
```

```
sudo systemctl enable --now marquee-web
```

Give the box a stable name (`winchester.local` via mDNS, or a DHCP
reservation) so the phone and widget do not chase a changing IP.

## 4. Refresh on a 6-hour cron

Alamo posts roughly a week out. Six hours is already generous; polling harder
buys nothing.

```
# crontab -u marquee -e
0 */6 * * * cd /opt/marquee && /usr/bin/python3 scripts/refresh.py >> logs/cron.log 2>&1
```

Offset the schedule off the hour if you like (`17 */6 * * *`) — there is no
reason for every self-hosted scraper on the internet to fire at :00.

A failed cycle does not blank the display. `refresh.py` retains the last good
snapshot, re-emits it with `stale: true`, and the header shows how old it is.
Only a successful fetch replaces the cache.

## 5. Phone

**Companion page** — open `http://winchester.local:8080` in Safari or Chrome,
then Share > Add to Home Screen. The manifest makes it launch standalone,
without browser chrome. This is where the full grid and the drill-in panels
live.

**Widget** — install Scriptable from the App Store, copy
`widget/marquee-widget.js` into its folder, and set `MARQUEE_URL` at the top of
the file to your box. Add a Scriptable widget to the home screen and point it
at the script.

The widget is the glance; tapping it opens the companion page. iOS widgets have
no in-widget interaction beyond a tap target, so the "why is this dimmed" panel
cannot live inside the widget itself — it lives one tap away.

Both surfaces render the verdict the fetcher already computed. Neither decides
anything on its own, so they cannot disagree.

## 6. Tuning the content signal

`config/marquee.toml` holds the keyword sets, the intensity ladder, and your
thresholds. `config/series.toml` holds the series treatments. Neither requires
touching Python.

After a few cycles, read the gap log:

```
cat logs/parse-failures.jsonl | python3 -m json.tool
```

It records the reason-string fragments the vocabulary did not recognise, the
strings it could not read at all, and series tags with no configured
treatment. That is the list to extend the config from. A title whose reason
string cannot be read shows as `unknown` rather than clean, so an empty log is
the goal.

## Current blocker

`scripts/refresh.py` will not produce real data yet. `marquee/adapters/alamo.py`
has its fetch layer written but not its field mapping, because endpoint
discovery has never run — see the README. On a box with normal outbound access:

```
python3 -m marquee.adapters.alamo discover
```

That prints a pretty-printed sample and a field inventory, and reports which of
the fields the display needs were actually found. Write `to_titles()` against
that inventory. It is the only function that needs writing — severity, series
resolution, the build pipeline, the page and the widget are all already written
against `marquee/model.py` and work unchanged the moment it returns real
`Title` objects.
