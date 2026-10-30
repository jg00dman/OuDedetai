#!/usr/bin/env python3
"""Summarise a log from log-wine-virtual.sh: committed memory per Wine process and phase.

    python3 analyse.py wine_virt_XXXX.log.gz

Streams the (gzipped) log line by line, so multi-GB logs are fine. Prints about 25 lines.
"Phase" = number of MARKER lines seen so far (press a key in log-wine-virtual.sh to add one).
PIDs are Wine's own, not Linux PIDs, so a renderer is identified by when it first appears.
"""
import collections
import gzip
import re
import sys

if len(sys.argv) != 2:
    sys.exit(__doc__)

pat = re.compile(r'([0-9a-f]{4}):([0-9a-f]{4}):trace:virtual:(\w+) (\S+) (\S+) ([0-9a-f]+) ([0-9a-f]+) ([0-9a-f]+)')
phase, first_phase = 0, {}
commit = collections.defaultdict(lambda: collections.defaultdict(int))
calls = collections.defaultdict(int)
big = collections.defaultdict(list)
for line in gzip.open(sys.argv[1], 'rt', errors='replace'):
    if 'MARKER' in line:
        phase += 1
        continue
    m = pat.search(line)
    if not m or m[3] != 'NtAllocateVirtualMemory':
        continue
    pid, size, typ, prot = m[1], int(m[6], 16), int(m[7], 16), int(m[8], 16)
    first_phase.setdefault(pid, phase)
    calls[pid] += 1
    if typ & 0x1000 and prot != 1:  # MEM_COMMIT, not PAGE_NOACCESS
        commit[pid][phase] += size
        if size >= 4 << 20:
            big[pid].append((size, m[5], hex(typ), hex(prot)))
print(f"markers seen: {phase}   pids: {len(first_phase)}\n")
rows = sorted(first_phase, key=lambda p: -sum(commit[p].values()))[:10]
print("pid   first-seen-phase  calls  committed_MB (by phase)")
for p in rows:
    print(f"{p}  {first_phase[p]:>10}  {calls[p]:>9}  {sum(commit[p].values())>>20:>8}   " +
          " ".join(f"p{k}:{v>>20}" for k, v in sorted(commit[p].items())))
new = [p for p in first_phase if first_phase[p] >= max(phase - 1, 1)]
print(f"\nprocesses first seen after the last marker: {new[:8]}")
for p in sorted(new, key=lambda p: -sum(commit[p].values()))[:3]:
    print(f"\nlargest commits in pid {p}:")
    for s, a, t, pr in sorted(big[p], reverse=True)[:6]:
        print(f"  {s>>20:>5}MB  addr={a}  type={t}  prot={pr}")
