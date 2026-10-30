#!/usr/bin/env python3
"""Per Wine process: total address space reserved, and the protection-table memory that implies.

    python3 reserved.py wine_virt_XXXX.log.gz

Wine keeps one protection byte per 4 KiB page (pages_vprot). Before the vprot patch, reserving
a range dirtied that table for the whole range, so predicted_table_MB ~= reserved / 4096.
Chromium renderers reserve ~1320 GiB (0x14a00000000), i.e. ~330 MB of table per renderer.

Counts NtAllocateVirtualMemory and (best effort) NtAllocateVirtualMemoryEx lines; the Ex
reservation is the big one, so if it never shows up, check the log line format against the regex.
"""
import collections
import gzip
import re
import sys

if len(sys.argv) != 2:
    sys.exit(__doc__)

pat = re.compile(r'([0-9a-f]{4}):[0-9a-f]{4}:trace:virtual:NtAllocateVirtualMemory(?:Ex)? '
                 r'(\S+) (\S+) ([0-9a-f]+) ([0-9a-f]+) ([0-9a-f]+)')
res, big = collections.defaultdict(int), collections.defaultdict(set)

for line in gzip.open(sys.argv[1], 'rt', errors='replace'):
    m = pat.search(line)
    if not m:
        continue
    size, typ = int(m[4], 16), int(m[5], 16)
    if typ & 0x2000:  # MEM_RESERVE
        res[m[1]] += size
        if size >= 1 << 30:
            big[m[1]].add(size >> 30)

print("pid   reserved_GiB  predicted_table_MB  sizes>=1GiB")
for p in sorted(res, key=lambda p: -res[p])[:8]:
    print(f"{p}  {res[p] >> 30:>10}  {res[p] // 4096 >> 20:>14}   {sorted(big[p])} GiB")
