#!/usr/bin/env python3
"""Turn off FastDDS data sharing inside booster-motion's bundled x86 libfastrtps.so.2.13 (Jetson only).

booster-motion runs under Box64 (x86_64) next to native arm64 simbridge/Maximus. FastDDS data sharing (on by default,
"AUTO", set in code, so the XML profile cannot turn it off) puts boost::interprocess mutexes and a segment manager in
/dev/shm/fast_datasharing_*; x86 and arm64 lay them out differently (pthread_mutex_t is 40 vs 48 bytes), and
booster-motion died with "Interprocess mutex timeout when locking". This makes the x86 side never offer data sharing:
DataWriterImpl/DataReaderImpl::check_datasharing_compatible(attrs, bool& out) become { out = false; return RETCODE_OK; }.
Every pair with booster-motion then uses the UDPv4 loopback transport. Native-native pairs are unchanged.
    python3 patch_fastrtps.py <in.so> <out.so>
"""
import sys

# File offsets (= virtual addresses in this library) from `nm -D --defined-only libfastrtps.so.2.13`
FUNCS = {0x436730: "DataWriterImpl::check_datasharing_compatible", 0x47E430: "DataReaderImpl::check_datasharing_compatible"}
PROLOGUE = bytes.fromhex("f30f1efa41")              # endbr64; push r12/r13 (the unpatched start of both)
PATCH = bytes.fromhex("c60200" "31c0" "c3")         # mov byte [rdx],0 ; xor eax,eax ; ret   (rdx = bool&, eax = RETCODE_OK)

src, dst = sys.argv[1], sys.argv[2]
b = bytearray(open(src, "rb").read())
for off, name in FUNCS.items():
    if b[off:off + len(PATCH)] == PATCH:
        print(f"{name}: already patched")
        continue
    assert b[off:off + len(PROLOGUE)] == PROLOGUE, f"{name}: unexpected bytes {b[off:off + 8].hex()} (other libfastrtps build?)"
    b[off:off + len(PATCH)] = PATCH
    print(f"{name}: patched at {off:#x}")
open(dst, "wb").write(b)
