# Winchester Marquee — Android home-screen widget

Replaces `widget/marquee-widget.js`, which is Scriptable and therefore iOS
only. This reads the same `data/marquee.json` and renders the same verdict the
fetcher already computed, so no surface can disagree with another about
whether a title is dimmed.

## Get the APK without a computer

Every push to `android/` builds a debug APK in CI. Open the repository's
**Actions** tab on the phone, take the newest **Build widget APK** run, and
download the `marquee-widget-debug` artifact. Unzip it and tap the APK;
Android will ask once for permission to install from that source.

Builds are signed with the checked-in `debug.keystore`, so a new APK installs
straight over the old one and the widget keeps its place on the home screen.

Then long-press the home screen → Widgets → Winchester Marquee.

## Build it yourself

1. Open the `android/` directory in Android Studio and let Gradle sync. It
   will fetch the Android Gradle Plugin and the Kotlin plugin.
2. Set where `web/` is being served from. In
   `app/src/main/java/com/winchester/marquee/MarqueeWidget.kt`:

   ```kotlin
   const val BASE_URL = "http://127.0.0.1:8080"
   ```

   The default is the phone itself, which is the usual setup: Termux runs the
   fetcher and a loopback server on the same device. Point it at a hostname
   instead if the fetcher lives on a Pi. Nothing else needs changing —
   cleartext is permitted in the base config, because scoping it to a
   `<domain>` list silently blocked loopback and produced a widget that said
   "cannot reach the box" while the browser loaded the same URL fine.
3. Build and install to your phone over USB, or `./gradlew installDebug`.
4. Long-press the home screen, choose Widgets, and drag "Winchester Marquee"
   out. It resizes.

## What it shows

One row per film, using its soonest showing that has not started yet, so once
the day's last screening has gone the row rolls onto tomorrow by itself. Six
rows fit; the rest are dropped rather than scrolled.

- **Dimmed titles** fade toward the flap colour. The sign stays lit — the same
  rule as the web board, where turning the whole tile down read as a broken
  bulb.
- **A trailing `?`** means the rating reason could not be read: unknown, not
  clean. Never silently treated as fine.
- **Tapping** opens `board.html`, which is where a verdict can explain itself.
  A widget has no room for the reason text.

## Deliberate limitations

**The sign is drawn smaller than the widget and scaled up.** Everything handed
to RemoteViews crosses a Binder transaction, and an oversized one is rejected
whole — not the picture, the entire update, leaving a widget that shows
nothing with no error anywhere a person would look. At native resolution on an
ordinary phone the bitmaps came to 4 MB against a budget of roughly 1 MB, and
that is exactly what happened. `SignRenderer.BUDGET_BYTES` caps it, so the
sign is softer than the screen could show and, in exchange, present.

Setting `ANIMATE_LAMPS = false` frees the three chase frames and buys back
some sharpness.


- **No chasing lamps.** A widget repaints on the host's schedule, not per
  frame, so the animated border on the web board has no equivalent here. The
  bezel is drawn as a static gradient.
- **No split-flap animation**, for the same reason.
- **Fixed row slots, not a collection.** Six `TextView` pairs that get shown
  or hidden, rather than a `RemoteViewsService` adapter. Far less machinery
  for a board that never shows many films, and nothing to go wrong in an
  adapter that cannot be debugged from a widget host.
- **Refresh is every 30 minutes**, the platform floor for
  `updatePeriodMillis`. The data changes every six hours, so this is already
  generous. A `com.winchester.marquee.REFRESH` broadcast forces one early if
  you want to drive it from Tasker or `adb`.
- **Stale beats blank.** A failed fetch falls back to the last good snapshot
  from `SharedPreferences` and marks the header `STALE`, the same rule the
  cron and the web page follow.

## Layout

```
app/src/main/
  AndroidManifest.xml
  java/com/winchester/marquee/MarqueeWidget.kt   the whole widget
  res/layout/widget_marquee.xml                  six row slots
  res/drawable/widget_sign.xml                   lit face + bezel
  res/xml/marquee_widget_info.xml                size, refresh period
  res/xml/network_security_config.xml            cleartext for your box only
  res/values/colors.xml                          same palette as the web board
```
