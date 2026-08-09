package com.winchester.marquee

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.PointF
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
    private const val BULB_HALO = 0x33FFD98A
    private const val HEADER = 0x18000000        // the band behind the name
    private const val RULE = 0x3317130C          // and the line under it

    /**
     * Chase circuits. Lamp n is wired to channel n % CHANNELS, and one channel
     * is live at a time — the mechanical arrangement, not a per-lamp
     * animation. Two channels cannot express direction, so three is the floor.
     */
    const val CHANNELS = 3

    /**
     * Characters of title a row should keep before the cells stop growing.
     * Below this a marquee is showing initials, which is not a glance at
     * anything.
     */
    private const val MIN_CHARS = 15

    /** Flaps in the time run. "12:00P" is the longest a showtime gets. */
    private const val TIME_CELLS = 6

    /** Lamp frames are drawn at this fraction of the sign, then scaled up. */
    private const val LAMP_SCALE = 0.28f

    /**
     * Total bitmap bytes one widget update may carry.
     *
     * Everything handed to RemoteViews crosses a Binder transaction, and the
     * system rejects an oversized one outright — not the picture, the whole
     * update. The widget then shows nothing at all, with no error anywhere a
     * person would look. Drawing at native resolution reached 4 MB on an
     * ordinary phone and did exactly that.
     *
     * So the sign is drawn small and scaled up by the ImageView. It is softer
     * than it would be at native resolution. It is also visible.
     */
    private const val BUDGET_BYTES = 800_000f

    /**
     * How far to shrink the render so the whole update fits the budget.
     *
     * Accounts for the lamp frames too, since they ride in the same
     * transaction — three of them at LAMP_SCALE in each dimension.
     */
    fun budgetScale(widthPx: Int, heightPx: Int, animating: Boolean): Float {
        val lampShare = if (animating) 3f * LAMP_SCALE * LAMP_SCALE else 0f
        val bytes = widthPx.toFloat() * heightPx * 4f * (1f + lampShare)
        if (bytes <= BUDGET_BYTES) return 1f
        return kotlin.math.sqrt(BUDGET_BYTES / bytes)
    }

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
        masthead: String,
        stamp: String,
        stale: Boolean,
        rows: List<Row>,
        message: String?
    ): Bitmap {
        // A floor in pixels, not dp: below this there is nothing legible to
        // draw whatever the screen's density claims.
        val w = max(widthPx, 240)
        val h = max(heightPx, 160)
        val bitmap = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        canvas.drawColor(WALL)

        // Everything below is sized as a fraction of the sign, never in dp.
        //
        // The bitmap is stretched to the widget by the ImageView, so a dp is
        // not a fixed size once it gets there — it is a fixed size *in the
        // bitmap*, which then scales by however wrong the launcher's reported
        // size was. This phone over-reports, so dp-sized cells rendered at
        // half their intended share of the sign: small letters, and rows
        // filling half the height with a void beneath. A proportion cannot
        // have that bug.
        val u = w / 100f                   // one percent of the sign's width
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)

        // --- the sign body -------------------------------------------------
        val frameInset = u * 0.6f
        val body = RectF(frameInset, frameInset, w - frameInset, h - frameInset)
        val corner = u * 3f

        paint.style = Paint.Style.FILL
        paint.color = FRAME
        canvas.drawRoundRect(body, corner, corner, paint)

        // The lit face, brightest where the lamps sit closest.
        val bulbLane = u * 2.8f
        val face = RectF(
            body.left + bulbLane, body.top + bulbLane,
            body.right - bulbLane, body.bottom - bulbLane
        )
        paint.shader = LinearGradient(
            0f, face.top, 0f, face.bottom, FACE_HOT, FACE, Shader.TileMode.CLAMP
        )
        canvas.drawRoundRect(face, u * 1.2f, u * 1.2f, paint)
        paint.shader = null

        drawBulbs(canvas, paint, body, bulbLane, u * 0.66f, u * 3.4f)

        // --- header band ---------------------------------------------------
        // A fixed 11dp masthead was a caption on a sign, not a sign's name.
        // The band scales with the object so it reads as the theatre's board
        // at any size the widget is dragged to.
        val pad = u * 2.5f
        val headerH = (face.width() * 0.11f)
            .coerceIn(face.height() * 0.07f, face.height() * 0.2f)
        val header = RectF(face.left, face.top, face.right, face.top + headerH)

        paint.color = HEADER
        canvas.drawRect(header, paint)
        paint.color = RULE
        paint.strokeWidth = max(u * 0.15f, 1f)
        canvas.drawLine(header.left + pad, header.bottom,
                        header.right - pad, header.bottom, paint)

        paint.typeface = mono
        paint.textAlign = Paint.Align.LEFT
        paint.textSize = headerH * 0.5f
        paint.color = INK
        val nameBase = header.centerY() - (paint.descent() + paint.ascent()) / 2f
        canvas.drawText(masthead, face.left + pad, nameBase, paint)
        val nameWidth = paint.measureText(masthead)

        // "NOW PLAYING" only when there is room for it beside the name, so a
        // narrow widget keeps the theatre rather than the caption.
        paint.textSize = headerH * 0.22f
        val kicker = "NOW PLAYING"
        paint.color = INK_SOFT
        if (nameWidth + paint.measureText(kicker) + pad * 3 < face.width() * 0.72f) {
            canvas.drawText(kicker, face.left + pad * 2 + nameWidth, nameBase, paint)
        }

        paint.color = if (stale) GLOW else INK_SOFT
        paint.textAlign = Paint.Align.RIGHT
        canvas.drawText(stamp, face.right - pad, nameBase, paint)
        paint.textAlign = Paint.Align.LEFT

        val y = header.bottom + u * 1.6f

        // --- a message instead of rows -------------------------------------
        if (message != null) {
            paint.textSize = headerH * 0.28f
            paint.color = INK_SOFT
            paint.typeface = Typeface.MONOSPACE
            var ty = y + headerH * 0.4f
            for (line in wrap(message, paint, face.width() - pad * 2)) {
                canvas.drawText(line, face.left + pad, ty, paint)
                ty += headerH * 0.38f
            }
            return bitmap
        }

        // --- rows of flaps -------------------------------------------------
        if (rows.isEmpty()) return bitmap

        val available = face.height() - (y - face.top) - pad
        val rowGap = u * 0.8f
        val minH = face.height() * 0.045f  // below this the letters stop reading
        val maxH = face.height() * 0.16f   // above it a tall widget just gapes

        // Fit the rows to the height, not a fixed row height to the rows.
        var visible = rows.size
        var cellH = (available - rowGap * (visible - 1)) / visible
        while (visible > 1 && cellH < minH) {
            visible--
            cellH = (available - rowGap * (visible - 1)) / visible
        }
        cellH = min(cellH, maxH)

        // Height is only half the constraint. Everything on a row scales with
        // cellH — flaps, time, marker — so a tall cell on a narrow sign spends
        // the whole width on a few big letters and truncates the film. Cap the
        // cell at whatever still leaves a title worth reading.
        //
        // The coefficient is the row's width in units of cellH: TIME_CELLS and
        // MIN_CHARS flaps at 0.52 each, plus the meta column, which is the
        // marker and a four-character day at 0.42 of the cell.
        val cellGap = max(u * 0.18f, 1f)
        val perMetaChar = 0.6f * 0.42f     // monospace advance, as a fraction
        val widthUnits = (TIME_CELLS + MIN_CHARS) * 0.52f + 6f * perMetaChar
        val widthCap = (face.width() - 3 * pad - MIN_CHARS * cellGap) / widthUnits
        cellH = min(cellH, max(widthCap, minH))

        val cellW = cellH * 0.52f          // a flap is taller than it is wide

        // Whatever height is left over goes into the gaps rather than into
        // taller cells: the cell is already as large as the width allows, so
        // growing it further would only take characters off the titles. The
        // rows spread down the sign instead of stacking at the top with a
        // void beneath them.
        val spread = if (visible > 1) {
            ((available - visible * cellH) / (visible - 1))
                .coerceIn(rowGap, cellH * 0.8f)
        } else rowGap

        // Fixed columns for the whole board, not one layout per row. The
        // runs then end on a straight edge and the markers line up, which is
        // what a board looks like; per-row widths left a ragged edge that read
        // as a mistake rather than a design.
        val rowPad = pad
        paint.typeface = mono

        // The meta column: the marker, and the day when it is not today.
        paint.textSize = cellH * 0.42f
        var metaCol = paint.measureText("? ")
        for (i in 0 until visible) {
            val day = rows[i].day
            if (day.isNotEmpty()) {
                metaCol = max(metaCol, paint.measureText("? ") + paint.measureText(day))
            }
        }

        val timeRun = TIME_CELLS * (cellW + cellGap) - cellGap
        val dayLeft = face.right - rowPad - metaCol
        val timeLeft = dayLeft - rowPad - timeRun
        val flapRight = timeLeft - rowPad

        for (i in 0 until visible) {
            val row = rows[i]
            val top = y + i * (cellH + spread)
            drawRow(canvas, paint, face, row, top, cellH, cellW, cellGap,
                    rowPad, flapRight, timeLeft, dayLeft)
        }
        return bitmap
    }

    /** One row: title flaps on the left, the marker and time on the right. */
    /**
     * A run of flaps carrying one string.
     *
     * Shared by the title and the time, because on the board they are the
     * same object — the web version flaps both, and a widget that flapped
     * only the title was a different machine wearing the same paint.
     */
    private fun drawFlaps(
        canvas: Canvas,
        paint: Paint,
        left: Float,
        top: Float,
        cells: Int,
        cellW: Float,
        cellH: Float,
        cellGap: Float,
        base: Float,
        text: String,
        ink: Int,
        alignRight: Boolean
    ) {
        val body = when {
            text.length > cells -> text.take(cells - 1) + "\u2026"
            alignRight -> text.padStart(cells, ' ')
            else -> text
        }

        paint.textAlign = Paint.Align.CENTER
        for (c in 0 until cells) {
            val x = left + c * (cellW + cellGap)
            val cell = RectF(x, top, x + cellW, top + cellH)

            paint.style = Paint.Style.FILL
            paint.shader = LinearGradient(
                0f, cell.top, 0f, cell.bottom, FLAP, FLAP_EDGE, Shader.TileMode.CLAMP
            )
            // Square, near enough. The web board's flaps are hard-cornered on
            // purpose; a hairline radius just takes the aliasing off.
            canvas.drawRoundRect(cell, 1f, 1f, paint)
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
        flapRight: Float,
        timeLeft: Float,
        dayLeft: Float
    ) {
        val ink = if (row.flagged) INK_DIM else INK
        paint.typeface = mono
        paint.textSize = cellH * 0.62f
        val base = top + cellH - (cellH - paint.textSize) / 2 - paint.descent() * 0.6f

        // The title.
        val runWidth = flapRight - (face.left + pad)
        val cells = floor((runWidth + cellGap) / (cellW + cellGap)).toInt()
        if (cells > 0) {
            drawFlaps(canvas, paint, face.left + pad, top, cells, cellW, cellH,
                      cellGap, base, row.title.uppercase(), ink, false)
        }

        // The time, flapped too, right-aligned so the digits line up column to
        // column exactly as they do on the board.
        drawFlaps(canvas, paint, timeLeft, top, TIME_CELLS, cellW, cellH,
                  cellGap, base, row.time, ink, true)

        // Day and marker stay plain text: on the board these live in the meta
        // column beside the flaps, not on them.
        paint.textSize = cellH * 0.42f
        paint.textAlign = Paint.Align.LEFT
        val metaBase = top + cellH - (cellH - paint.textSize) / 2 - paint.descent() * 0.6f
        var x = dayLeft
        if (row.unknown) {
            // Never truncated, never squeezed out: an unreadable rating must
            // not be able to look like a clean one.
            paint.color = GLOW
            canvas.drawText("?", x, metaBase, paint)
            x += paint.measureText("? ")
        }
        if (row.day.isNotEmpty()) {
            paint.color = if (row.flagged) INK_DIM else INK_SOFT
            canvas.drawText(row.day, x, metaBase, paint)
        }
    }

    /**
     * Lamps around the perimeter.
     *
     * Every third lamp is bright, the pattern a mechanical chaser leaves when
     * one of its three circuits is live. On the web board that pattern
     * rotates; here it is frozen, because a widget is repainted by its host
     * every half hour and animation is not on offer.
     */
    /**
     * Where every lamp sits, walked clockwise from the top-left corner.
     *
     * Position in this list is the lamp's wiring: lamp n is on channel
     * n % CHANNELS. That is how a mechanical chaser is actually built — the
     * bulbs are wired to a few circuits in rotation and a rotating drum
     * energises one circuit at a time, so the light appears to travel without
     * anything moving. Three is the floor: with two, "forwards" and
     * "backwards" look identical.
     *
     * Both the static sign and the animation frames walk this same list, so
     * the lit lamps always land exactly on top of the unlit ones.
     */
    private fun bulbPositions(body: RectF, lane: Float, spacing: Float): List<PointF> {
        val inset = lane / 2f
        val left = body.left + inset
        val right = body.right - inset
        val top = body.top + inset
        val bottom = body.bottom - inset
        val w = right - left
        val h = bottom - top
        val perimeter = 2 * (w + h)

        // The lamp count is forced to a multiple of CHANNELS and the spacing
        // adjusted to suit, rather than the other way round. Walking the
        // perimeter at a fixed pitch leaves a remainder where the loop closes,
        // and at the wrap the chase either doubles a lamp or skips one — a
        // visible hitch in one corner, at whatever widget sizes happen to
        // divide badly. Spacing is the forgiving quantity here; the wiring is
        // not.
        var count = max(CHANNELS * 2, (perimeter / spacing).toInt())
        count -= count % CHANNELS
        val step = perimeter / count

        val out = ArrayList<PointF>(count)
        for (i in 0 until count) {
            var d = i * step
            when {
                d < w -> out.add(PointF(left + d, top))
                d < w + h -> { d -= w; out.add(PointF(right, top + d)) }
                d < 2 * w + h -> { d -= w + h; out.add(PointF(right - d, bottom)) }
                else -> { d -= 2 * w + h; out.add(PointF(left, bottom - d)) }
            }
        }
        return out
    }

    private fun drawBulbs(
        canvas: Canvas,
        paint: Paint,
        body: RectF,
        lane: Float,
        radius: Float,
        spacing: Float
    ) {
        paint.style = Paint.Style.FILL
        paint.color = BULB_DIM
        // The static layer draws every lamp unlit. The lit ones are painted
        // over it by the flipper frames, so a phone that will not animate
        // still shows a complete ring rather than gaps.
        for (p in bulbPositions(body, lane, spacing)) {
            canvas.drawCircle(p.x, p.y, radius, paint)
        }
    }

    /**
     * One frame of the chase: only the lamps on the live channel, everything
     * else transparent.
     *
     * Drawn at reduced scale on purpose. Bitmaps handed to RemoteViews share a
     * transaction budget of about a megabyte, and three full-size copies of
     * the sign would exceed it — but a frame of this is a few dozen dots, so
     * scaling it up costs nothing anyone can see.
     */
    fun lamps(widthPx: Int, heightPx: Int, phase: Int): Bitmap {
        val w = max((widthPx * LAMP_SCALE).toInt(), 1)
        val h = max((heightPx * LAMP_SCALE).toInt(), 1)
        val bitmap = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)

        // The same proportions render() uses. They have to be proportions and
        // not dp, or the lit dots would land beside the unlit ring rather than
        // on it — this frame is drawn at LAMP_SCALE and stretched back over a
        // sign drawn at full size.
        val u = w / 100f
        val frameInset = u * 0.6f
        val body = RectF(frameInset, frameInset, w - frameInset, h - frameInset)

        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        paint.style = Paint.Style.FILL
        val positions = bulbPositions(body, u * 2.8f, u * 3.4f)
        val radius = u * 0.66f

        for ((n, p) in positions.withIndex()) {
            if (n % CHANNELS != phase) continue
            paint.color = BULB
            canvas.drawCircle(p.x, p.y, radius, paint)
            // The filament's spill onto the frame around it.
            paint.color = BULB_HALO
            canvas.drawCircle(p.x, p.y, radius * 2.1f, paint)
        }
        return bitmap
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
