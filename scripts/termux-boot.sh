#!/data/data/com.termux/files/usr/bin/sh
#
# Start the marquee when the phone boots.
#
# Install:
#   pkg install termux-services cronie termux-api
#   mkdir -p ~/.termux/boot
#   cp ~/Marquee/scripts/termux-boot.sh ~/.termux/boot/marquee
#   chmod +x ~/.termux/boot/marquee
#
# then install the Termux:Boot app from F-Droid and open it once, so Android
# grants it permission to run at start. Termux:Boot will not fire until it has
# been opened at least once after install.
#
# NOT TESTED. This was written without a device to run it on. The shape is
# right and the commands are the documented ones, but expect to fix a path on
# the first boot.

set -e

ROOT="$HOME/Marquee"

# Android will otherwise suspend the process the moment the screen goes off,
# which stops both the server and the cron timer. The lock is cheap; the
# server is idle except when the page is open.
termux-wake-lock 2>/dev/null || true

mkdir -p "$ROOT/logs"

# crond runs the 6-hour refresh. See docs/deploy.md for the crontab line.
sv-enable crond 2>/dev/null || sv up crond 2>/dev/null || true

# One refresh at boot, so a phone that was off overnight is current by the
# time anyone looks at it rather than waiting for the next cron slot.
cd "$ROOT" && python3 scripts/refresh.py >> logs/cron.log 2>&1 || true

# Bound to loopback: the phone is both the box and the display, so there is no
# reason to put this on the wifi. Change to 0.0.0.0 if you want to reach it
# from a laptop on the same network.
cd "$ROOT/web" && exec python3 -m http.server 8080 --bind 127.0.0.1 \
    >> "$ROOT/logs/web.log" 2>&1
