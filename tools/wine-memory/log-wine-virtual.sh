#!/bin/bash
# Run Logos under Wine with virtual-memory tracing (+virtual) and save a gzipped log.
#
# The trace is written to RAM (/dev/shm) while Logos runs, because writing it to disk
# slows Wine down enough to distort what you are measuring. Press a key to insert a
# MARKER line; analyse.py uses the markers to split the log into phases (e.g. "settled
# after start", "after opening a panel"). Quit Logos normally to finish.
#
# Usage:
#   ./log-wine-virtual.sh                       # OuDedetai's default Wine + bottle
#   WINE_EXE=/path/to/wine64 PREFIX=/path/to/bottle ./log-wine-virtual.sh
#   OUT_DIR=~/logs MAX_MB=1000 ./log-wine-virtual.sh
#
# Environment:
#   WINE_EXE   wine binary to run   (default: $DATA_DIR/bin/wine64)
#   PREFIX     wine prefix          (default: $DATA_DIR/wine64_bottle/)
#   DATA_DIR   OuDedetai data dir   (default: ${XDG_DATA_HOME:-~/.local/share}/FaithLife-Community/oudedetai/data)
#   OUT_DIR    where to save the .log.gz   (default: $HOME)
#   MAX_MB     stop if the raw log reaches this size   (default: 2000)

set -u

DATA_DIR=${DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/FaithLife-Community/oudedetai/data}
WINE_EXE=${WINE_EXE:-$DATA_DIR/bin/wine64}
PREFIX=${PREFIX:-$DATA_DIR/wine64_bottle/}
OUT_DIR=${OUT_DIR:-$HOME}
MAX_MB=${MAX_MB:-2000}

if [ ! -x "$WINE_EXE" ]; then echo "Wine binary not found or not executable: $WINE_EXE"; exit 1; fi
if [ ! -d "$PREFIX" ]; then echo "Wine prefix not found: $PREFIX"; exit 1; fi

if pgrep -f 'Logos\.exe|LogosCEF\.exe' >/dev/null; then
    echo "Logos is already running. Quit it first (pkill -f 'Logos\.exe|LogosCEF\.exe'; pkill -x wineserver)."
    exit 1
fi

LOGFILE=/dev/shm/wine_virt.log
: > "$LOGFILE"
insert_marker() { echo "==== MARKER $(date '+%H:%M:%S') ====" >> "$LOGFILE"; }

LOGOS_EXE=$(find "$PREFIX" -wholename '*Logos/Logos.exe' | head -1)
if [ -z "$LOGOS_EXE" ]; then echo "Logos.exe not found under $PREFIX"; exit 1; fi
echo "Logos: $LOGOS_EXE"
STOP=
trap 'STOP=1' INT

echo "Starting Wine with virtual-memory logging..."
# Do not use -all here: it drops the pid:tid prefix the analysers rely on.
( WINEDEBUG=+pid,+tid,+timestamp,+virtual WINEPREFIX="$PREFIX" "$WINE_EXE" "$LOGOS_EXE" 2>&1 \
  | grep --line-buffered -E 'trace:virtual:(NtAllocateVirtualMemory|NtFreeVirtualMemory|NtProtectVirtualMemory|NtMapViewOfSection|NtUnmapViewOfSection)' \
  >> "$LOGFILE" ) &

# Wait for the real Logos processes (the launcher can exit early).
for _ in $(seq 1 90); do
    pgrep -f 'LogosCEF\.exe|System.Logos\.exe' >/dev/null && break
    sleep 1
done
sleep 3
if ! grep -m1 -E '[0-9a-f]{4}:[0-9a-f]{4}:trace:virtual' "$LOGFILE" >/dev/null; then
    echo "WARNING: log lines have no pid:tid prefix. First line:"
    head -1 "$LOGFILE" | cut -c1-150
    STOP=1
fi

[ -z "$STOP" ] && echo "Logos is running. Press a key for a marker. Quit Logos normally to finish."
while [ -z "$STOP" ] && pgrep -f 'Logos\.exe|LogosCEF\.exe' >/dev/null; do
    if read -r -t 1 -s -n 1 _key; then
        insert_marker
        echo "Marker added ($(du -h "$LOGFILE" | cut -f1) so far)."
    fi
    if [ "$(( $(stat -c %s "$LOGFILE") / 1048576 ))" -ge "$MAX_MB" ]; then
        echo "Log reached ${MAX_MB}MB, stopping."; break
    fi
done

echo "Stopping Wine and saving the log..."
pkill -f 'Logos\.exe|LogosCEF\.exe'; sleep 3; pkill -x wineserver; sleep 2
OUT="$OUT_DIR/wine_virt_$(date +%Y%m%d_%H%M%S).log.gz"
gzip -1 -c "$LOGFILE" > "$OUT"
ls -lh "$LOGFILE" "$OUT"
rm -f "$LOGFILE"
