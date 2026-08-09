# Winchester Marquee — Android home-screen widget

Replaces `widget/marquee-widget.js`, which is Scriptable and therefore iOS
only. This reads the same `data/marquee.json` and renders the same verdict the
fetcher already computed, so no surface can disagree with another about
whether a title is dimmed.

## This has never been compiled

It was written without an Android SDK available. The XML is well-formed and
every `R.id`, `R.color`, `@string` and `@drawable` reference has been checked
against the resources that define it — but nothing here has been through a
compiler or run on a device. Expect to fix something on the first build.

## Build it

1. Open the `android/` directory in Android Studio and let Gradle sync. It
   will fetch the Android Gradle Plugin and the Kotlin plugin.
2. Set your box's address. In
   `app/src/main/java/com/winchester/marquee/MarqueeWidget.kt`:

   ```kotlin
   const val BASE_URL = "http://winchester.local:8080"
   ```

   If you use a bare IP rather than a hostname, add it to
   `app/src/main/res/xml/network_security_config.xml` as well — the box serves
   plain HTTP, and cleartext is permitted per-domain rather than app-wide.
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
