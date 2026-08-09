package com.winchester.marquee

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.Typeface
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min

/**
 * Draws the marquee sign as a bitmap.
 *
 * RemoteViews cannot host a custom view, so a widget built from TextViews can
 * only ever be a list of strings — which is what it was, and why it looked
 * nothing like the board. An ImageView it can host, so the sign is drawn with
 * Canvas and handed over as a bitmap.
 *
 * The palette is board.css's default theme, restated here because a widget
 * process cannot read the page's stylesheet. If the two drift, this is the
 * copy that is wrong.
 *
 * One thing deliberately not attempted: the flaps do not animate. A widget is
 * repainted by the host at its own pace, not sixty times a second, so a roll
 * would be a slideshow. The tiles are drawn settled.
 */
object SignRenderer {

    private const val WALL = 0x00000000        // transparent: the launcher's own wallpaper
    private const val FACE = 0xFFE2CB99.toInt()
    private const val FACE_HOT = 0xFFF2E3BA.toInt()
    private const val FRAME = 0xFF17130C.toInt()
    private const val BULB = 0xFFFFD98A.toInt()
    private const val BULB_DIM = 0xFF8A7548.toInt()
    private const val FLAP = 0xFFFCF2D8.toInt()
    private const val FLAP_EDGE = 0xFFEBDCB2.toInt()
    private const val INK = 0xFF17130C.toInt()
    private const val INK_DIM = 0xFF8A7C62.toInt()
    private const val INK_SOFT = 0xA317130C.toInt()
    // The hinge across each flap. At full strength it crossed every glyph and
    // read as a strikethrough rather than a fold, so it is faint here — the
    // web board's seam sits on a much larger tile.
    private const val SEAM = 0x4214100A
    private const val GLOW = 0xFFB8600C.toInt()

    /** One line of the board. */
    data class Row(
        val title: String,
        val time: String,
        val day: String,
        val flagged: Boolean,
        val unknown: Boolean
    )

    private val mono: Typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)

    fun render(
        widthPx: Int,
        heightPx: Int,
        density: Float,
        masthead: String,
        stamp: String,
        stale: Boolean,
        rows: List<Row>,
        message: String?
    ): Bitmap {
        val w = max(widthPx, (140 * density).toInt())
        val h = max(heightPx, (90 * density).toInt())
        val bitmap = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        canvas.drawColor(WALL)

        val dp = { v: Float -> v * density }
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)

        // --- the sign body -------------------------------------------------
        val frameInset = dp(2f)
        val body = RectF(frameInset, frameInset, w - frameInset, h - frameInset)
        val corner = dp(10f)

        paint.style = Paint.Style.FILL
        paint.color = FRAME
        canvas.drawRoundRect(body, corner, corner, paint)

        // The lit face, brightest where the lamps sit closest.
        val bulbLane = dp(9f)
        val face = RectF(
            body.left + bulbLane, body.top + bulbLane,
            body.right - bulbLane, body.bottom - bulbLane
        )
        paint.shader = LinearGradient(
            0f, face.top, 0f, face.bottom, FACE_HOT, FACE, Shader.TileMode.CLAMP
        )
        canvas.drawRoundRect(face, dp(4f), dp(4f), paint)
        paint.shader = null

        drawBulbs(canvas, paint, body, bulbLane, dp(2.1f), dp(11f))

        // --- masthead ------------------------------------------------------
        val pad = dp(8f)
        var y = face.top + pad
        paint.typeface = mono
        paint.textSize = dp(11f)
        paint.color = INK
        paint.textAlign = Paint.Align.LEFT
        val mastBase = y - paint.fontMetrics.ascent
        canvas.drawText(masthead, face.left + pad, mastBase, paint)

        paint.textSize = dp(8f)
        paint.color = if (stale) GLOW else INK_SOFT
        paint.textAlign = Paint.Align.RIGHT
        canvas.drawText(stamp, face.right - pad, mastBase, paint)
        paint.textAlign = Paint.Align.LEFT

        y = mastBase + dp(6f)

        // --- a message instead of rows -------------------------------------
        if (message != null) {
            paint.textSize = dp(9.5f)
            paint.color = INK_SOFT
            paint.typeface = Typeface.MONOSPACE
            var ty = y + dp(10f)
            for (line in wrap(message, paint, face.width() - pad * 2)) {
                canvas.drawText(line, face.left + pad, ty, paint)
                ty += dp(13f)
            }
            return bitmap
        }

        // --- rows of flaps -------------------------------------------------
        if (rows.isEmpty()) return bitmap

        val available = face.height() - (y - face.top) - pad
        val rowGap = dp(2.5f)
        val minH = dp(11f)                 // below this the letters stop reading
        val maxH = dp(20f)                 // above it a tall widget just gapes

        // Fit the rows to the height, rather than a fixed row height to the
        // rows: a fixed 17dp left two thirds of a short widget empty while
        // still overflowing a shorter one.
        var visible = rows.size
        var cellH = (available - rowGap * (visible - 1)) / visible
        while (visible > 1 && cellH < minH) {
            visible--
            cellH = (available - rowGap * (visible - 1)) / visible
        }
        cellH = min(cellH, maxH)

        val cellW = cellH * 0.52f          // a flap is taller than it is wide
        val cellGap = max(dp(0.6f), 1f)

        for (i in 0 until visible) {
            val row = rows[i]
            val top = y + i * (cellH + rowGap)
            drawRow(canvas, paint, face, row, top, cellH, cellW, cellGap, dp(6f), density)
        }
        return bitmap
    }

    /** One row: title flaps on the left, the marker and time on the right. */
    private fun drawRow(
        canvas: Canvas,
        paint: Paint,
        face: RectF,
        row: Row,
        top: Float,
        cellH: Float,
        cellW: Float,
        cellGap: Float,
        pad: Float,
        density: Float
    ) {
        val ink = if (row.flagged) INK_DIM else INK

        // The time is plain text, not flaps — it is a label on the board, and
        // flapping it would cost eight cells the title needs more.
        paint.typeface = mono
        paint.textSize = cellH * 0.62f
        paint.color = ink
        paint.textAlign = Paint.Align.RIGHT
        val base = top + cellH - (cellH - paint.textSize) / 2 - paint.descent() * 0.6f
        val timeText = "${row.day} ${row.time}"
        canvas.drawText(timeText, face.right - pad, base, paint)
        val timeW = paint.measureText(timeText)

        // The unknown marker sits between title and time and is drawn before
        // the title is measured, so it can never be squeezed out by a long
        // name. Truncating it would make an unreadable rating look clean.
        var rightEdge = face.right - pad - timeW - pad
        if (row.unknown) {
            paint.color = GLOW
            canvas.drawText("?", rightEdge, base, paint)
            rightEdge -= paint.measureText("?") + pad * 0.7f
        }

        val runWidth = rightEdge - (face.left + pad)
        if (runWidth <= cellW) return
        val cells = floor((runWidth + cellGap) / (cellW + cellGap)).toInt()
        if (cells <= 0) return

        val text = row.title.uppercase()
        val body = if (text.length > cells) text.take(cells - 1) + "…" else text

        paint.textAlign = Paint.Align.CENTER
        for (c in 0 until cells) {
            val x = face.left + pad + c * (cellW + cellGap)
            val cell = RectF(x, top, x + cellW, top + cellH)

            paint.style = Paint.Style.FILL
            paint.shader = LinearGradient(
                0f, cell.top, 0f, cell.bottom, FLAP, FLAP_EDGE, Shader.TileMode.CLAMP
            )
            canvas.drawRoundRect(cell, density, density, paint)
            paint.shader = null

            // The hinge across the middle: the thing that makes it a flap
            // rather than a box.
            paint.color = SEAM
            paint.strokeWidth = 1f
            canvas.drawLine(cell.left, cell.centerY(), cell.right, cell.centerY(), paint)

            val ch = if (c < body.length) body[c] else ' '
            if (ch != ' ') {
                paint.color = ink
                canvas.drawText(ch.toString(), cell.centerX(), base, paint)
            }
        }
        paint.textAlign = Paint.Align.LEFT
    }

    /**
     * Lamps around the perimeter.
     *
     * Every third lamp is bright, the pattern a mechanical chaser leaves when
     * one of its three circuits is live. On the web board that pattern
     * rotates; here it is frozen, because a widget is repainted by its host
     * every half hour and animation is not on offer.
     */
    private fun drawBulbs(
        canvas: Canvas,
        paint: Paint,
        body: RectF,
        lane: Float,
        radius: Float,
        spacing: Float
    ) {
        paint.style = Paint.Style.FILL
        val inset = lane / 2f
        val left = body.left + inset
        val right = body.right - inset
        val top = body.top + inset
        val bottom = body.bottom - inset

        var n = 0
        val plot = { x: Float, yy: Float ->
            paint.color = if (n % 3 == 0) BULB else BULB_DIM
            canvas.drawCircle(x, yy, radius, paint)
            n++
        }

        var x = left
        while (x <= right) { plot(x, top); x += spacing }
        var yy = top + spacing
        while (yy <= bottom) { plot(right, yy); yy += spacing }
        x = right - spacing
        while (x >= left) { plot(x, bottom); x -= spacing }
        yy = bottom - spacing
        while (yy > top) { plot(left, yy); yy -= spacing }
    }

    private fun wrap(text: String, paint: Paint, width: Float): List<String> {
        val out = ArrayList<String>()
        var line = StringBuilder()
        for (word in text.split(" ")) {
            val candidate = if (line.isEmpty()) word else "$line $word"
            if (paint.measureText(candidate) > width && line.isNotEmpty()) {
                out.add(line.toString())
                line = StringBuilder(word)
            } else {
                line = StringBuilder(candidate)
            }
        }
        if (line.isNotEmpty()) out.add(line.toString())
        return out
    }
}
