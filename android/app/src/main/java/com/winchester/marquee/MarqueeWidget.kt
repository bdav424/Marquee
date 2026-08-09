package com.winchester.marquee

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.widget.RemoteViews
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.time.Duration
import java.time.OffsetDateTime
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.concurrent.thread

/**
 * Home-screen widget for the Winchester marquee.
 *
 * Reads the same cached snapshot the web board reads and renders the verdict
 * already computed by the fetcher. It never decides anything itself, so the
 * widget cannot disagree with the grid or the board about whether a title is
 * dimmed.
 *
 * The sign itself is drawn by SignRenderer into a bitmap. RemoteViews cannot
 * host a custom view, so a widget assembled from TextViews can only be a list
 * of strings — which is what this was, and why it looked nothing like the
 * board it is supposed to be a glance at.
 *
 * Replaces the Scriptable script in widget/, which is iOS-only. Built by
 * .github/workflows/android.yml on every push to android/, which is also how
 * to get an installable APK without Android Studio. See android/README.md.
 */
class MarqueeWidget : AppWidgetProvider() {

    companion object {
        /**
         * Where web/ is being served from.
         *
         * Defaults to the phone itself, which is the common setup: Termux
         * runs the fetcher and a loopback HTTP server, so the widget, the page
         * and the box are all one device and nothing touches the network.
         * Point it at a hostname instead if the fetcher lives on a Pi.
         */
        const val BASE_URL = "http://127.0.0.1:8080"

        private const val DATA_PATH = "/data/marquee.json"
        private const val PAGE_PATH = "/board.html"
        private const val PREFS = "marquee"
        private const val KEY_LAST_GOOD = "last_good_json"
        private const val ACTION_REFRESH = "com.winchester.marquee.REFRESH"

        /** Used when the host does not report a size. */
        private const val FALLBACK_W_DP = 250
        private const val FALLBACK_H_DP = 110

        /** More rows than this and the flaps stop being legible. */
        private const val MAX_ROWS = 8

        /** The chase frames, one per SignRenderer channel. */
        private val LAMP_IDS = intArrayOf(R.id.lamp0, R.id.lamp1, R.id.lamp2)

        /**
         * Set false to stop the lamps chasing.
         *
         * The animation is the launcher redrawing the widget every few hundred
         * milliseconds for as long as the home screen is on view. That is a
         * real if small battery cost, and it is the first thing to turn off if
         * the phone starts feeling warm.
         */
        private const val ANIMATE_LAMPS = true
    }

    override fun onUpdate(
        context: Context,
        manager: AppWidgetManager,
        widgetIds: IntArray
    ) {
        refresh(context, manager, widgetIds)
    }

    override fun onAppWidgetOptionsChanged(
        context: Context,
        manager: AppWidgetManager,
        widgetId: Int,
        newOptions: Bundle
    ) {
        // Resizing changes how many rows fit and how long a title can be, and
        // the bitmap is drawn at a fixed size, so it has to be redrawn.
        refresh(context, manager, intArrayOf(widgetId))
    }

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        if (intent.action == ACTION_REFRESH) {
            val manager = AppWidgetManager.getInstance(context)
            refresh(
                context, manager,
                manager.getAppWidgetIds(ComponentName(context, MarqueeWidget::class.java))
            )
        }
    }

    private fun refresh(
        context: Context,
        manager: AppWidgetManager,
        widgetIds: IntArray
    ) {
        if (widgetIds.isEmpty()) return
        // Widget callbacks run on the main thread and the host kills slow
        // ones, so the fetch goes to a background thread and the views are
        // pushed when it returns.
        thread {
            val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val result = fetch()
            var body = result.body
            var stale = false

            if (body == null) {
                // Stale beats blank, the same rule the cron and the page use.
                body = prefs.getString(KEY_LAST_GOOD, null)
                stale = true
            } else {
                prefs.edit().putString(KEY_LAST_GOOD, body).apply()
            }

            // Each widget can be a different size, so each gets its own draw.
            for (id in widgetIds) {
                manager.updateAppWidget(
                    id, render(context, manager, id, body, stale, result.problem)
                )
            }
        }
    }

    /** What went wrong, in the words the person holding the phone needs. */
    private class Fetched(val body: String?, val problem: String?)

    private fun fetch(): Fetched = try {
        val connection = (URL(BASE_URL + DATA_PATH).openConnection() as HttpURLConnection)
        connection.connectTimeout = 8000
        connection.readTimeout = 8000
        connection.useCaches = false
        val code = connection.responseCode
        when {
            code == 404 -> Fetched(null, "Server is up but has no snapshot yet. Run refresh.py.")
            code >= 400 -> Fetched(null, "Server answered HTTP $code.")
            else -> Fetched(connection.inputStream.bufferedReader().use { it.readText() }, null)
        }
    } catch (e: java.net.ConnectException) {
        // Overwhelmingly the common case: nothing is listening, because the
        // Termux server is not running. Saying so beats "cannot reach".
        Fetched(null, "Nothing is listening on $BASE_URL. Is the server running?")
    } catch (e: java.net.SocketTimeoutException) {
        Fetched(null, "$BASE_URL timed out.")
    } catch (e: java.io.IOException) {
        Fetched(null, "Cannot read $BASE_URL: ${e.javaClass.simpleName}.")
    } catch (e: Exception) {
        Fetched(null, "${e.javaClass.simpleName}: ${e.message ?: "no detail"}")
    }

    private fun render(
        context: Context,
        manager: AppWidgetManager,
        widgetId: Int,
        body: String?,
        stale: Boolean,
        problem: String?
    ): RemoteViews {
        val views = RemoteViews(context.packageName, R.layout.widget_marquee)

        // Tapping the sign opens the board, which is where a verdict can
        // explain itself. A widget has no room for the reason text.
        views.setOnClickPendingIntent(
            R.id.widget_root,
            PendingIntent.getActivity(
                context, 0,
                Intent(Intent.ACTION_VIEW, Uri.parse(BASE_URL + PAGE_PATH)),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )
        )
        // The corner retries now. Without it a transient failure sits there
        // until the 30-minute update period comes round, which is a long time
        // to stare at NO SIGNAL after starting the server.
        views.setOnClickPendingIntent(
            R.id.retry,
            PendingIntent.getBroadcast(
                context, 1,
                Intent(context, MarqueeWidget::class.java).setAction(ACTION_REFRESH),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )
        )

        val metrics = context.resources.displayMetrics
        val options = manager.getAppWidgetOptions(widgetId)
        val wDp = options.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 0)
            .takeIf { it > 0 } ?: FALLBACK_W_DP
        val hDp = options.getInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT, 0)
            .takeIf { it > 0 } ?: FALLBACK_H_DP
        val wPx = (wDp * metrics.density).toInt()
        val hPx = (hDp * metrics.density).toInt()

        if (ANIMATE_LAMPS) {
            for ((phase, id) in LAMP_IDS.withIndex()) {
                views.setImageViewBitmap(
                    id, SignRenderer.lamps(wPx, hPx, metrics.density, phase)
                )
            }
        } else {
            // Hiding the flipper leaves the sign's own unlit ring showing,
            // which is a sign with the chaser switched off rather than a sign
            // missing its lamps.
            views.setViewVisibility(R.id.lamps, View.GONE)
        }

        if (body == null) {
            views.setImageViewBitmap(
                R.id.sign,
                SignRenderer.render(
                    wPx, hPx, metrics.density, "WINCHESTER", "NO SIGNAL", true,
                    emptyList(), (problem ?: "No cached snapshot yet.") +
                        " Tap the top right to retry."
                )
            )
            return views
        }

        val snapshot: JSONObject
        val rows: List<Row>
        try {
            snapshot = JSONObject(body)
            rows = upcoming(snapshot)
        } catch (e: Exception) {
            views.setImageViewBitmap(
                R.id.sign,
                SignRenderer.render(
                    wPx, hPx, metrics.density, "WINCHESTER", "BAD DATA", true,
                    emptyList(), "The snapshot could not be read."
                )
            )
            return views
        }

        val isStale = stale || snapshot.optBoolean("stale", false)
        val age = relativeAge(snapshot.optString("fetched_at", ""))
        val stamp = if (isStale) "STALE $age" else "UPDATED $age"

        // The masthead follows the market, so a widget pointed at another
        // city does not keep claiming to be Winchester.
        val masthead = snapshot.optJSONObject("market")?.optString("name")
            ?.substringBefore(",")?.uppercase(Locale.US) ?: "WINCHESTER"

        views.setImageViewBitmap(
            R.id.sign,
            SignRenderer.render(
                wPx, hPx, metrics.density, masthead, stamp, isStale,
                rows.take(MAX_ROWS).map {
                    SignRenderer.Row(it.name, it.time, it.day, it.flagged, it.unknown)
                },
                if (rows.isEmpty()) "Nothing left on the board." else null
            )
        )
        return views
    }

    private data class Row(
        val name: String,
        val time: String,
        val day: String,
        val flagged: Boolean,
        val unknown: Boolean,
        val at: OffsetDateTime
    )

    /**
     * One entry per title, using its soonest showing that has not started.
     * Once the day's last screening has gone the row rolls onto tomorrow by
     * itself, so the widget never advertises a screening already missed.
     */
    private fun upcoming(snapshot: JSONObject): List<Row> {
        val now = OffsetDateTime.now()
        val titles = snapshot.optJSONArray("titles") ?: return emptyList()
        val rows = ArrayList<Row>()

        for (i in 0 until titles.length()) {
            val title = titles.optJSONObject(i) ?: continue
            val showings = title.optJSONArray("showings") ?: continue

            var soonest: OffsetDateTime? = null
            for (j in 0 until showings.length()) {
                val raw = showings.optJSONObject(j)?.optString("showtime") ?: continue
                val at = try {
                    OffsetDateTime.parse(raw)
                } catch (e: Exception) {
                    continue
                }
                if (at.isBefore(now)) continue
                if (soonest == null || at.isBefore(soonest)) soonest = at
            }
            val at = soonest ?: continue

            rows.add(
                Row(
                    // display_name drops Alamo's booking decoration; a widget
                    // row has no characters to spare on a strand name.
                    name = title.optString(
                        "display_name",
                        title.optString("name", title.optString("slug", "?"))
                    ),
                    time = at.format(DateTimeFormatter.ofPattern("h:mma", Locale.US))
                        .replace("AM", "A").replace("PM", "P"),
                    day = dayLabel(at),
                    flagged = title.optBoolean("flagged", false),
                    unknown = !title.optBoolean("reason_parsed", false),
                    at = at
                )
            )
        }
        rows.sortBy { it.at }
        return rows
    }

    private fun dayLabel(at: OffsetDateTime): String {
        val today = ZonedDateTime.now().toLocalDate()
        val date = at.toLocalDate()
        return when (date) {
            today -> "TODAY"
            today.plusDays(1) -> "TMRW"
            else -> date.dayOfWeek
                .getDisplayName(java.time.format.TextStyle.SHORT, Locale.US)
                .uppercase(Locale.US)
        }
    }

    private fun relativeAge(iso: String): String {
        if (iso.isEmpty()) return ""
        return try {
            val minutes = Duration.between(OffsetDateTime.parse(iso), OffsetDateTime.now())
                .toMinutes()
                .coerceAtLeast(0)
            when {
                minutes < 60 -> "${minutes}M"
                minutes < 60 * 24 -> "${minutes / 60}H"
                else -> "${minutes / (60 * 24)}D"
            }
        } catch (e: Exception) {
            ""
        }
    }
}
