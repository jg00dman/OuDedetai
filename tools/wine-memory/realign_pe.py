#!/usr/bin/env python3
"""Re-lay out a 64-bit PE so each section's raw data starts on a 4 KiB boundary
(FileAlignment = SectionAlignment = 0x1000).

Why: Wine can only mmap a PE section if its file offset is page-aligned. With the
usual 0x200 FileAlignment, Wine instead read()s the section into private anonymous
memory, so every process that loads the DLL holds its own copy.

EXPERIMENTAL. Always run on a copy:

    realign_pe.py libcef.dll libcef.realigned.dll

Dropped on purpose: Authenticode signature, debug-directory entry, checksum
(all three would otherwise point at stale file offsets).
"""
import struct
import sys

PAGE = 0x1000


def up(x, a=PAGE):
    return (x + a - 1) & ~(a - 1)


def realign(d: bytes) -> bytes:
    d = bytes(d)
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    if d[pe:pe + 4] != b"PE\0\0":
        raise SystemExit("not a PE file")
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    optsz = struct.unpack_from("<H", d, pe + 20)[0]
    opt = pe + 24
    if struct.unpack_from("<H", d, opt)[0] != 0x20B:
        raise SystemExit("only 64-bit PE (PE32+) is supported")
    sect_align, file_align = struct.unpack_from("<II", d, opt + 32)
    if sect_align != PAGE:
        raise SystemExit(f"unexpected SectionAlignment {sect_align:#x}")
    hdr_size = struct.unpack_from("<I", d, opt + 60)[0]
    nrva = struct.unpack_from("<I", d, opt + 108)[0]
    sh = opt + optsz

    secs = []
    for i in range(nsec):
        o = sh + 40 * i
        vsize, va, rsize, rptr = struct.unpack_from("<IIII", d, o + 8)
        secs.append({"o": o, "rsize": rsize, "rptr": rptr})

    new_hdr = up(hdr_size)
    if sh + 40 * nsec > new_hdr:
        raise SystemExit("section table does not fit in the new header area")

    out = bytearray(d[:hdr_size]) + bytearray(new_hdr - hdr_size)
    for s in sorted((s for s in secs if s["rsize"]), key=lambda s: s["rptr"]):
        data = d[s["rptr"]:s["rptr"] + s["rsize"]]
        data = data + bytes(s["rsize"] - len(data))  # tolerate truncated files
        assert len(out) % PAGE == 0
        s["new_rptr"] = len(out)
        s["new_rsize"] = up(len(data))
        out += data + bytes(s["new_rsize"] - len(data))

    struct.pack_into("<I", out, opt + 36, PAGE)       # FileAlignment
    struct.pack_into("<I", out, opt + 60, new_hdr)    # SizeOfHeaders
    struct.pack_into("<I", out, opt + 64, 0)          # CheckSum
    for s in secs:
        if s["rsize"]:
            struct.pack_into("<II", out, s["o"] + 16, s["new_rsize"], s["new_rptr"])
    dd = opt + 112
    for idx in (4, 6):  # 4 = security (file offset!), 6 = debug
        if idx < nrva:
            struct.pack_into("<II", out, dd + 8 * idx, 0, 0)
    return bytes(out)


def main():
    if len(sys.argv) != 3 or sys.argv[1] == sys.argv[2]:
        raise SystemExit("usage: realign_pe.py <in.dll> <out.dll>  (different files)")
    with open(sys.argv[1], "rb") as f:
        out = realign(f.read())
    with open(sys.argv[2], "wb") as f:
        f.write(out)
    print(f"wrote {sys.argv[2]} ({len(out)} bytes)")


if __name__ == "__main__":
    main()
