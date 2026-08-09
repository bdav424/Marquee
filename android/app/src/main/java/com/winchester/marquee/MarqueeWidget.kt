package com.winchester.marquee

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.content.Intent
import android.net.Uri
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
 * Replaces the Scriptable script in widget/, which is iOS-only.
 *
 * NOT COMPILED. This was written without an Android SDK available, so it has
 * never been built or run. Treat it as reviewed, not working: open the
 * android/ directory in Android Studio, let it sync, and expect to fix
 * something on the first build.
 */
class MarqueeWidget : AppWidgetProvider() {

    companion object {
        /**
         * Where web/ is being served from.
         *
         * Defaults to the phone itself, which is the common setup: Termux
         * runs the fetcher and a loopback HTTP server, so the widget, the
         * page and the box are all one device and nothing touches the
         * network. Point it at a hostname instead if you run the fetcher on
         * a Pi — and add that hostname to network_security_config.xml, or
         * Android will refuse the cleartext request.
         */
        const val BASE_URL = "http://127.0.0.1:8080"

        private const val DATA_PATH = "/data/marquee.json"
        private const val PAGE_PATH = "/board.html"
        private const val PREFS = "marquee"
        private const val KEY_LAST_GOOD = "last_good_json"
        private const val ACTION_REFRESH = "com.winchester.marquee.REFRESH"

        /** Row slots declared in widget_marquee.xml. */
        private val ROW_IDS = intArrayOf(
            R.id.row0, R.id.row1, R.id.row2, R.id.row3, R.id.row4, R.id.row5
        )
        private val TITLE_IDS = intArrayOf(
            R.id.title0, R.id.title1, R.id.title2,
            R.id.title3, R.id.title4, R.id.title5
        )
        private val TIME_IDS = intArrayOf(
            R.id.time0, R.id.time1, R.id.time2,
            R.id.time3, R.id.time4, R.id.time5
        )
    }

    override fun onUpdate(
        context: Context,
        manager: AppWidgetManager,
        widgetIds: IntArray
    ) {
        refresh(context, manager, widgetIds)
    }

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        if (intent.action == ACTION_REFRESH) {
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(
                android.content.ComponentName(context, MarqueeWidget::class.java)
            )
            refresh(context, manager, ids)
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

            val views = render(context, body, stale, result.problem)
            for (id in widgetIds) manager.updateAppWidget(id, views)
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
        Fetched(null, "Nothing is listening on $BASE_URL — is the server running?")
    } catch (e: java.net.SocketTimeoutException) {
        Fetched(null, "$BASE_URL timed out.")
    } catch (e: java.io.IOException) {
        // Cleartext blocked by the network security config lands here, and it
        // is invisible otherwise — the host has to be listed in
        // network_security_config.xml or Android refuses plain HTTP outright.
        Fetched(null, "Cannot read $BASE_URL: ${e.javaClass.simpleName}. " +
            "If you changed the host, add it to network_security_config.xml.")
    } catch (e: Exception) {
        Fetched(null, "${e.javaClass.simpleName}: ${e.message ?: "no detail"}")
    }

    private fun render(
        context: Context,
        body: String?,
        stale: Boolean,
        problem: String?
    ): RemoteViews {
        val views = RemoteViews(context.packageName, R.layout.widget_marquee)

        // Tapping opens the board, which is where a verdict can explain
        // itself. A widget has no room for the reason text.
        val open = PendingIntent.getActivity(
            context, 0,
            Intent(Intent.ACTION_VIEW, Uri.parse(BASE_URL + PAGE_PATH)),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        views.setOnClickPendingIntent(R.id.widget_root, open)

        for (id in ROW_IDS) views.setViewVisibility(id, View.GONE)

        if (body == null) {
            views.setTextViewText(R.id.stamp, "NO SIGNAL")
            views.setViewVisibility(R.id.empty, View.VISIBLE)
            // Never just "cannot reach": with no cache to fall back on this
            // text is the only thing to debug from, and the widget cannot
            // show a stack trace.
            views.setTextViewText(R.id.empty, problem ?: "No cached snapshot yet.")
            return views
        }

        val rows: List<Row>
        val snapshot: JSONObject
        try {
            snapshot = JSONObject(body)
            rows = upcoming(snapshot)
        } catch (e: Exception) {
            views.setTextViewText(R.id.stamp, "BAD DATA")
            views.setViewVisibility(R.id.empty, View.VISIBLE)
            views.setTextViewText(R.id.empty, "Snapshot could not be read.")
            return views
        }

        val fetchedAt = snapshot.optString("fetched_at", "")
        val age = relativeAge(fetchedAt)
        val isStale = stale || snapshot.optBoolean("stale", false)
        views.setTextViewText(R.id.stamp, if (isStale) "STALE $age" else "UPDATED $age")
        views.setTextColor(
            R.id.stamp,
            context.getColor(if (isStale) R.color.alert else R.color.ink_soft)
        )

        if (rows.isEmpty()) {
            views.setViewVisibility(R.id.empty, View.VISIBLE)
            views.setTextViewText(R.id.empty, "Nothing left on the board.")
            return views
        }
        views.setViewVisibility(R.id.empty, View.GONE)

        val ink = context.getColor(R.color.flap_ink)
        val inkDim = context.getColor(R.color.flap_ink_dim)

        for ((slot, row) in rows.take(ROW_IDS.size).withIndex()) {
            views.setViewVisibility(ROW_IDS[slot], View.VISIBLE)
            // A trailing ? means the rating reason could not be read: unknown,
            // not clean. Never silently treated as fine.
            val mark = if (row.unknown) "  ?" else ""
            views.setTextViewText(TITLE_IDS[slot], row.name.uppercase(Locale.US) + mark)
            views.setTextViewText(TIME_IDS[slot], "${row.day} ${row.time}")

            // Dimming fades the letters, it does not darken the sign.
            val colour = if (row.flagged) inkDim else ink
            views.setTextColor(TITLE_IDS[slot], colour)
            views.setTextColor(TIME_IDS[slot], colour)
        }
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
