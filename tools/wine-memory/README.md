# Wine memory tools (OuDedetai issue #452 / Wine bug 58805)

Scripts used to find and measure why each Chromium (CEF) renderer process in Logos
uses so much memory under Wine. They are generic: nothing here depends on a particular
user, home directory or Wine build. Defaults point at OuDedetai's own Wine and bottle
(`~/.local/share/FaithLife-Community/oudedetai/data`); override with environment variables.

## The findings

Two independent causes, both in Wine rather than in Logos or CEF:

1. **Protection table, ~330 MB per renderer.** Chromium renderers reserve a single
   0x14a00000000-byte (~1320 GiB) `PAGE_NOACCESS` range. Wine keeps one protection byte per
   4 KiB page (`pages_vprot` in `dlls/ntdll/unix/virtual.c`) and `set_page_vprot()` memsets
   the whole range, dirtying ~330 MiB of zero pages in every renderer.
2. **Private copies of `libcef.dll`, ~220 MB per renderer.** `libcef.dll` (~235 MB) has a
   file alignment of 0x200, so its big sections are not at host-page-aligned file offsets.
   `map_file_into_view()` cannot `mmap` them, falls back to `pread()` into private memory,
   once per process.

Prototype Wine patches (not for merge, under discussion upstream) address each cause, and a
DLL workaround (`realign_pe.py`) addresses the second without patching Wine.

Measured on one machine (Logos, wine-devel 10.13 AppImage, 16 GB, 15 CEF processes), renderer
`Pss_Anon`: several hundred MB each before; about 65 MB each with the patches, using
the unmodified `libcef.dll`. Treat these as a single-machine result, not a benchmark.

## Tools

| Tool | What it does |
|------|--------------|
| `measure-processes.sh` | Per-process Pss / Pss_Anon / Pss_Shmem of running CEF processes. The before/after number. |
| `log-wine-virtual.sh` | Runs Logos with Wine's `+virtual` trace written to RAM, with key-press markers; saves a `.log.gz`. |
| `analyse.py` | Committed memory per Wine process and per marker phase, from that log. |
| `reserved.py` | Reserved address space per process and the protection-table memory it implies. |
| `bigvma.py` | Which running processes hold >=128 GiB mappings (only renderers do). |
| `realign_pe.py` | Rewrites a 64-bit PE with 4 KiB file alignment, so Wine can share its sections. Workaround for cause 2. **Experimental**; drops the signature, debug directory and checksum. Always run on a copy. |

### Measuring

```bash
./tools/wine-memory/measure-processes.sh          # with Logos open and a few panels loaded
```

Compare `Anon_MB` for the renderer rows between a stock Wine and a patched one. Total `Pss`
at the bottom is the fair system-wide figure. Shared DLL pages served by a patched
wineserver appear under `Shmem_MB`, not `Pss_File` (they live on tmpfs).

### Tracing

```bash
./tools/wine-memory/log-wine-virtual.sh
# wait for Logos to settle, press a key (marker 1); open a panel, wait, press a key (marker 2)
# quit Logos; a ~/wine_virt_*.log.gz file is written
python3 tools/wine-memory/analyse.py  ~/wine_virt_*.log.gz
python3 tools/wine-memory/reserved.py ~/wine_virt_*.log.gz
```

Logs can reach several GB; both analysers stream, so memory use stays small. Tracing slows
Wine, so do not use it for the memory numbers above.

### Realigning a DLL (workaround)

```bash
cp libcef.dll libcef.dll.orig
python3 tools/wine-memory/realign_pe.py libcef.dll.orig libcef.dll
```

Close Logos first. Roughly 30% less total memory in our test, because the sections become
file-backed and shared. Changing a vendor DLL is a workaround; the Wine patches are the fix.

## Testing a patched Wine inside an AppImage

An AppImage is a squashfs. Extract it, replace the built files, repack:

```bash
./wine-devel_X-x86_64.AppImage --appimage-extract          # creates squashfs-root/
R=squashfs-root/opt/wine-devel
cp ~/wine/dlls/ntdll/ntdll.so $R/lib/wine/x86_64-unix/ntdll.so
cp ~/wine/server/wineserver   $R/bin/wineserver            # needed by the shared-section patch
ARCH=x86_64 appimagetool --no-appstream squashfs-root my-wine.AppImage
```

Check the glibc a host build needs before sharing it:

```bash
objdump -T $R/bin/wineserver $R/lib/wine/x86_64-unix/ntdll.so | grep -o 'GLIBC_[0-9.]*' | sort -Vu | tail -1
```

A build made on a recent distro may need a newer glibc than the AppImage's original files;
build in an older-distro container (e.g. `ubuntu:22.04`) if broader compatibility matters.

To run it by hand against a bottle, without logging:

```bash
WINEDEBUG=-all WINEPREFIX=/path/to/bottle ./squashfs-root/AppRun /path/to/Logos.exe
```

`AppRun` already runs `wine`, so do not add `wine64` as an extra argument.

## Patches

The Wine patches themselves belong next to these tools once they are final, as
`git format-patch` output in `tools/wine-memory/patches/`. Status and discussion: Wine bug 58805.
Both are prototypes; the second changes the loader and the wineserver, so only run it on
a machine where a crash costs you nothing.
