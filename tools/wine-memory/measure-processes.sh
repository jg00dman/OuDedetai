#!/bin/bash
# Per-process memory of running CEF processes, from /proc/PID/smaps_rollup.
#
#   ./measure-processes.sh [pgrep-pattern]       # default pattern: LogosCEF.exe
#
# Columns: Pss (proportional set size, shared pages divided between sharers),
# Pss_Anon (private anonymous memory), Pss_Shmem (shared tmpfs pages such as the wineserver's
# shared image copies, divided between sharers). Compare Pss_Anon with and without a patched
# Wine; sum the Pss column for a fair total across processes.
#
# Note: pages_vprot/pages-table cost shows up as Pss_Anon; shared DLL copies served from
# the wineserver's tmpmap-* files show up as Pss_Shmem, not Pss_File.

pattern=${1:-LogosCEF.exe}
total=0
printf '%-8s %-18s %8s %9s %10s\n' PID TYPE "Pss_MB" "Anon_MB" "Shmem_MB"
for p in $(pgrep -f "$pattern"); do
    [ -r "/proc/$p/smaps_rollup" ] || continue
    t=$(tr '\0' ' ' < "/proc/$p/cmdline" | grep -o -- '--type=[a-z-]*' | head -1)
    read -r pss anon shm < <(awk '/^Pss:/{p=$2} /^Pss_Anon:/{a=$2} /^Pss_Shmem:/{s=$2} END{print p+0, a+0, s+0}' "/proc/$p/smaps_rollup")
    printf '%-8s %-18s %8d %9d %10d\n' "$p" "${t:-main}" $((pss/1024)) $((anon/1024)) $((shm/1024))
    total=$((total + pss))
done
echo "total Pss: $((total/1024)) MB"
