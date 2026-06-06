import struct
import hashlib
import sys

BUILD = r'build\TextEx\TextEx.exe'
DIST  = r'dist\TextEx\TextEx.exe'

# ── Method 1: Custom Python parser ────────────────────────────────────────────
def parse_pe_subsystem(path):
    with open(path, 'rb') as f:
        raw = f.read()

    # e_magic check
    dos_magic = raw[0:2]

    # e_lfanew: PE header offset, at DOS offset 0x3C (4-byte LE int)
    pe_offset = struct.unpack_from('<I', raw, 0x3C)[0]

    # PE signature at pe_offset
    pe_sig = raw[pe_offset : pe_offset + 4]

    # Subsystem: IMAGE_OPTIONAL_HEADER.Subsystem
    # In the PE Optional Header:
    #   PE signature:          4 bytes  (pe_offset)
    #   COFF header:          20 bytes  (pe_offset + 4)
    #   Optional header magic: 2 bytes  (pe_offset + 24)
    # For both PE32 (0x10B) and PE32+ (0x20B), Subsystem is at offset 68
    # from the start of the Optional Header, i.e. pe_offset + 4 + 20 + 68
    # = pe_offset + 92 = pe_offset + 0x5C
    subsystem_offset = pe_offset + 0x5C
    subsystem_value  = struct.unpack_from('<H', raw, subsystem_offset)[0]

    opt_magic = struct.unpack_from('<H', raw, pe_offset + 24)[0]

    return {
        'path':              path,
        'dos_magic':         dos_magic.hex(),
        'pe_offset':         pe_offset,
        'pe_offset_hex':     hex(pe_offset),
        'pe_sig':            pe_sig,
        'pe_sig_valid':      pe_sig == b'PE\x00\x00',
        'opt_magic':         hex(opt_magic),
        'subsystem_offset':  subsystem_offset,
        'subsystem_offset_hex': hex(subsystem_offset),
        'subsystem_value':   subsystem_value,
        'file_size':         len(raw),
    }

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def first_diff(path_a, path_b):
    with open(path_a, 'rb') as fa, open(path_b, 'rb') as fb:
        offset = 0
        while True:
            ca = fa.read(4096)
            cb = fb.read(4096)
            if not ca and not cb:
                return None  # identical up to min length
            # Compare byte by byte within this block
            length = min(len(ca), len(cb))
            for i in range(length):
                if ca[i] != cb[i]:
                    return offset + i
            offset += length
            if len(ca) != len(cb):
                return offset  # one file is longer — differs here


print("=" * 70)
print("METHOD 1: CUSTOM PYTHON STRUCT PARSER")
print("=" * 70)

for path in [BUILD, DIST]:
    r = parse_pe_subsystem(path)
    print()
    print(f"File:              {r['path']}")
    print(f"File size (bytes): {r['file_size']:,}")
    print(f"DOS magic:         {r['dos_magic']}")
    print(f"PE offset (0x3C):  {r['pe_offset']} ({r['pe_offset_hex']})")
    print(f"PE sig at offset:  {r['pe_sig']} valid={r['pe_sig_valid']}")
    print(f"Opt header magic:  {r['opt_magic']}")
    print(f"Subsystem offset:  {r['subsystem_offset']} ({r['subsystem_offset_hex']})")
    print(f"Subsystem value:   {r['subsystem_value']}")

print()
print("=" * 70)
print("METHOD 2: pefile MODULE")
print("=" * 70)

try:
    import pefile
    for path in [BUILD, DIST]:
        pe = pefile.PE(path, fast_load=True)
        sub = pe.OPTIONAL_HEADER.Subsystem
        pe_off = pe.DOS_HEADER.e_lfanew
        # pefile stores the file offset of OPTIONAL_HEADER
        opt_off = pe.OPTIONAL_HEADER.get_file_offset()
        # Subsystem is at fixed offset within OPTIONAL_HEADER structure
        # pefile tracks it; compute offset = opt_off + field offset within struct
        sub_off = pe.OPTIONAL_HEADER.__file_offset__ + pe.OPTIONAL_HEADER.__field_offsets__['Subsystem']
        print()
        print(f"File:              {path}")
        print(f"e_lfanew (PE off): {pe_off} ({hex(pe_off)})")
        print(f"Subsystem offset:  {sub_off} ({hex(sub_off)})")
        print(f"Subsystem value:   {sub}")
        pe.close()
except ImportError:
    print("pefile not installed in this venv")
except Exception as e:
    print(f"pefile error: {e}")

print()
print("=" * 70)
print("SHA256 HASHES")
print("=" * 70)

h_build = sha256(BUILD)
h_dist  = sha256(DIST)
print()
print(f"build\\TextEx\\TextEx.exe: {h_build}")
print(f"dist\\TextEx\\TextEx.exe:  {h_dist}")
print(f"Hashes match:           {h_build == h_dist}")

if h_build != h_dist:
    print()
    print("=" * 70)
    print("FIRST DIFFERING BYTE OFFSET")
    print("=" * 70)
    diff_off = first_diff(BUILD, DIST)
    print()
    if diff_off is not None:
        print(f"First differing offset: {diff_off} ({hex(diff_off)})")
        # Show context
        with open(BUILD, 'rb') as f:
            f.seek(max(0, diff_off - 8))
            b_ctx = f.read(32)
        with open(DIST, 'rb') as f:
            f.seek(max(0, diff_off - 8))
            d_ctx = f.read(32)
        ctx_start = max(0, diff_off - 8)
        print(f"Context window starts at offset: {ctx_start} ({hex(ctx_start)})")
        print(f"BUILD bytes: {b_ctx.hex()}")
        print(f"DIST  bytes: {d_ctx.hex()}")
    else:
        print("No differing byte found in common region.")
