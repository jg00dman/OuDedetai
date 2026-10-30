#!/usr/bin/env python3
"""List which running CEF processes hold huge (>=128 GiB) address-space mappings.

    python3 bigvma.py [pgrep-pattern]       # default pattern: LogosCEF\\.exe

Run with Logos open. Reads /proc/PID/maps and /proc/PID/cmdline of Linux processes.
Used to show that only renderer processes carry the ~1320 GiB reservation.
"""
import re
import subprocess
import sys

pattern = sys.argv[1] if len(sys.argv) > 1 else r'LogosCEF\.exe'
try:
    pids = subprocess.check_output(['pgrep', '-f', pattern]).split()
except subprocess.CalledProcessError:
    sys.exit(f"no processes match {pattern!r}")

for p in pids:
    pid = int(p)
    try:
        cmd = open(f'/proc/{pid}/cmdline', 'rb').read().replace(b'\0', b' ').decode(errors='ignore')
        m = re.search(r'--type=[a-z-]+', cmd)
        big = 0
        for line in open(f'/proc/{pid}/maps'):
            a, b = line.split()[0].split('-')
            n = int(b, 16) - int(a, 16)
            if n >= 1 << 37:
                big += n
        print(pid, m.group(0) if m else '', f'mappings>=128GiB: {big >> 30} GiB')
    except Exception as e:  # process may have exited, or be unreadable
        print(pid, 'error', e)
