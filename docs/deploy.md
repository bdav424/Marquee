# Deploying the marquee

Two ways to run this, and the second one is probably what you want.

**On the phone itself**, under Termux. The phone is both the box and the
display, nothing goes on the network at all, and it works away from home
because it is not talking to anything. Jump to [On a phone](#on-a-phone).

**On a small always-on box** on the LAN (a Pi is plenty) serving `web/` over
HTTP, with the phone as a client. Better if you want several devices reading
the same snapshot, or the phone's battery left alone. That is the rest of this
section.

Either way nothing is exposed to the internet and nothing needs an account.

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

**Widget (iOS)** — install Scriptable from the App Store, copy
`widget/marquee-widget.js` into its folder, and set `MARQUEE_URL` at the top of
the file to your box. Add a Scriptable widget to the home screen and point it
at the script.

**Widget (Android)** — `android/` holds an AppWidgetProvider that reads the
same JSON. It has never been compiled: open the directory in Android Studio,
set `BASE_URL` in `MarqueeWidget.kt`, and build. Until then the home-screen
shortcut to the page is the Android equivalent, and it loses nothing except
the glance.

The widget is the glance; tapping it opens the companion page. iOS widgets have
no in-widget interaction beyond a tap target, so the "why is this dimmed" panel
cannot live inside the widget itself — it lives one tap away.

Both surfaces render the verdict the fetcher already computed. Neither decides
anything on its own, so they cannot disagree.

## 6. Your thresholds

Most tuning does not need a text editor. The gear icon on the grid opens a
settings sheet: per-category thresholds, the Horror backstop, whether to flag
unreadable ratings, and whether flagged titles dim or hide. It is stored on
the device and applies to both the grid and the board, so two people using the
same box can disagree.

Hiding always shows a count and a way back. `config/marquee.toml` remains the
default for a fresh device.

## 7. Tuning the vocabulary

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

## On a phone

Termux, no root, no server anywhere else. The phone fetches the schedule,
builds the snapshot and serves it to itself over loopback.

```
pkg install python git cronie termux-services termux-api
git clone https://github.com/bdav424/Marquee ~/Marquee
cd ~/Marquee && python3 -m unittest discover -s tests -t .
```

Set the TMDB key so enrichment runs — put it in `~/.bashrc` so cron inherits
it, or in the crontab line directly:

```
echo 'export TMDB_API_KEY=your_key_here' >> ~/.bashrc
```

First snapshot, then serve:

```
python3 scripts/refresh.py
cd web && python3 -m http.server 8080 --bind 127.0.0.1
```

Open `http://localhost:8080` in Chrome, then **⋮ > Add to Home screen**. The
manifest launches it standalone, so it opens like an app rather than a tab.
`board.html` is the split-flap sign, `index.html` is the poster grid with the
drill-in panels; the link in the corner swaps between them.

### Making it survive a reboot

`scripts/termux-boot.sh` takes a wake lock, starts `crond`, runs one refresh
and starts the server. Install Termux:Boot from F-Droid, **open it once** so
Android grants it permission, then:

```
mkdir -p ~/.termux/boot
cp ~/Marquee/scripts/termux-boot.sh ~/.termux/boot/marquee
chmod +x ~/.termux/boot/marquee
```

And the refresh itself:

```
crontab -e
17 */6 * * * cd ~/Marquee && python3 scripts/refresh.py >> logs/cron.log 2>&1
```

Android is aggressive about killing background processes. Exempt Termux from
battery optimisation in Android settings, or the server will be gone by
morning and the page will fail to load rather than show stale data.

> The boot script has never been run — it was written without a device. The
> commands are the documented Termux ones but expect to fix something the
> first time.

## Day to day

Nothing, most of the time. The cron refreshes every six hours and the page
reads a local file.

The one recurring task is the reason book. Each cycle writes
`logs/needs-reason.txt` with a paste-ready block, ordered newest first:

```
"Mystery Machine" = ""
"The Odyssey" = ""  # 2026
"In the Mouth of Madness" = ""  # 1994
```

Look the top few up at filmratings.com in a browser, paste the sentence
**verbatim** between the quotes, and drop the block into `config/reasons.toml`
under `[reasons]`. The parser reads the wording — `strong bloody violence` and
`some violence` score differently — so paraphrasing changes the verdict.

Stop when the years start looking old. A question mark on a revival screening
is an honest answer, and pre-1990 films are dropped from the list entirely
because CARA never wrote a descriptor for them.

Changes take effect on the next refresh; run `python3 scripts/refresh.py` if
you do not want to wait for the cron.
