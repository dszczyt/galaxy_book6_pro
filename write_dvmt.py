#!/usr/bin/env python3
"""Patch DVMT Pre-Allocated in SaSetup NVRAM variable via /dev/mtd0.

Computes ALL offsets at runtime from the live flash — no hardcoded positions.
Locates the active NVAR entry (next=0xffffff) for SaSetup, verifies structure,
then patches SaSetup[0x05] from 0x02 (64MB) to 0x04 (128MB).

Usage:
  sudo python3 write_dvmt.py          # dry run (default)
  sudo python3 write_dvmt.py --write  # actually write
"""
import os, sys, struct, fcntl

# ── Config ───────────────────────────────────────────────────────────────────
SASETUP_GUID   = '72C5E28C-7783-43A1-8767-FAD73FCCAFA4'
SASETUP_NAME   = b'SaSetup'
IFR_VAR_OFFSET = 0x05    # byte index within SaSetup = DVMT Pre-Allocated
EXPECTED_OLD   = 0x02    # 64MB
NEW_VALUE      = 0x04    # 128MB
MTD_DEV        = '/dev/mtd0'
SECTOR_SIZE    = 4096

MEMERASE  = 0x40084d02   # _IOW('M', 2, struct erase_info_user { u32 start, u32 length })
MEMUNLOCK = 0x40084d04

DRY_RUN = '--write' not in sys.argv

# ── NVAR constants (from CHIPSEC / Insyde BIOS) ───────────────────────────────
NVAR_SIG         = b'NVAR'
NVAR_HDR_FMT     = '<4sH3sB'   # sig(4) + size(2) + next(3) + attrs(1) = 10 bytes
NVAR_HDR_SZ      = struct.calcsize(NVAR_HDR_FMT)  # = 10
NVRAM_ATTR_DATA  = 0x08   # DATA-only entry (no name, no GUID prefix)
NVRAM_ATTR_ASCII = 0x02   # name is ASCII (not UCS-2)
NVRAM_NEXT_END   = 0xffffff  # sentinel: this entry is the latest in chain

# ── EFI Firmware Volume constants ─────────────────────────────────────────────
EFI_FVH_SIG      = b'_FVH'    # at offset 40 in FV header
NVAR_FS_GUID     = bytes.fromhex('a3b9f5ce6d477f499fdc43e098144e00')[::-1]  # CEF5B9A3... LE

# ── Step 1: read full flash ───────────────────────────────────────────────────
print(f'[1] Reading {MTD_DEV}...', flush=True)
with open(MTD_DEV, 'rb') as f:
    flash = bytearray(f.read())
print(f'    Flash size: {len(flash):,} bytes ({len(flash)//1024//1024} MB)')

# ── Step 2: find NVAR store ────────────────────────────────────────────────────
# Scan for FV headers; find the one containing the NVAR filesystem file
print('[2] Locating NVAR variable store...')

def iter_fv(data):
    """Yield (fv_offset, fv_size) for all EFI Firmware Volumes in data."""
    pos = 0
    while pos + 56 < len(data):
        sig_off = pos + 40
        if data[sig_off:sig_off+4] == b'_FVH':
            fv_size = struct.unpack_from('<Q', data, pos + 32)[0]
            if 0 < fv_size <= len(data) - pos:
                yield pos, fv_size
            pos += max(fv_size, 1)
        else:
            # Skip to next aligned candidate
            pos += 4
    return

NVAR_FS_GUID_BE = bytes.fromhex('CEF5B9A3476D497F9FDCE98143E0422C')
NVAR_FS_GUID_LE = bytes([
    NVAR_FS_GUID_BE[3], NVAR_FS_GUID_BE[2], NVAR_FS_GUID_BE[1], NVAR_FS_GUID_BE[0],
    NVAR_FS_GUID_BE[5], NVAR_FS_GUID_BE[4],
    NVAR_FS_GUID_BE[7], NVAR_FS_GUID_BE[6],
    *NVAR_FS_GUID_BE[8:]
])

# Use CHIPSEC library (already proven to work)
sys.path.insert(0, '/usr/lib/python3.14/site-packages')
from chipsec.library.uefi.varstore import getNVstore_NVAR

store_off, store_sz, _ = getNVstore_NVAR(bytes(flash))
if store_off < 0:
    print('ERROR: NVAR store not found — aborting')
    sys.exit(1)
print(f'    NVAR store: abs 0x{store_off:x}–0x{store_off+store_sz:x} ({store_sz//1024}KB)')

# ── Step 3: find SaSetup entries, follow chain to active entry ────────────────
print('[3] Scanning NVAR entries for SaSetup chain...')

def parse_nvar_header(data, abs_off):
    raw = data[abs_off:abs_off + NVAR_HDR_SZ]
    if len(raw) < NVAR_HDR_SZ:
        return None
    sig, size, next3_bytes, attrs = struct.unpack(NVAR_HDR_FMT, raw)
    next_val = next3_bytes[0] | (next3_bytes[1] << 8) | (next3_bytes[2] << 16)
    return sig, size, next_val, attrs

entries = []  # (abs_off, size, next_val, attrs, data_abs_off)
pos = store_off
store_end = store_off + store_sz

while pos + NVAR_HDR_SZ < store_end:
    hdr = parse_nvar_header(flash, pos)
    if hdr is None:
        break
    sig, size, next_val, attrs = hdr
    if sig != NVAR_SIG:
        pos += 1
        continue
    if size < NVAR_HDR_SZ or pos + size > store_end:
        pos += 1
        continue

    data_off = pos + NVAR_HDR_SZ
    is_data_only = bool(attrs & NVRAM_ATTR_DATA)
    is_ascii     = bool(attrs & NVRAM_ATTR_ASCII)

    if is_data_only:
        # No GUID index, no name — data starts right after header
        var_name   = None
        data_start = data_off
    else:
        # 1-byte GUID index, then null-terminated name (ASCII or UCS-2)
        guid_idx   = flash[data_off]
        name_start = data_off + 1
        if is_ascii:
            end = flash.index(b'\x00', name_start)
            var_name   = bytes(flash[name_start:end])
            data_start = end + 1
        else:
            # UCS-2: scan for 2-byte null
            p = name_start
            while p + 1 < pos + size:
                if flash[p] == 0 and flash[p+1] == 0:
                    break
                p += 2
            var_name   = bytes(flash[name_start:p]).decode('utf-16-le', errors='replace').encode()
            data_start = p + 2

    entries.append({
        'abs': pos, 'size': size, 'next': next_val, 'attrs': attrs,
        'name': var_name, 'data_abs': data_start,
        'is_data_only': is_data_only,
    })
    pos += size

# Find the named SaSetup entry
named = [e for e in entries if e['name'] == SASETUP_NAME]
if not named:
    print(f'ERROR: no NVAR entry named "{SASETUP_NAME.decode()}" found — aborting')
    sys.exit(1)
print(f'    Found {len(named)} named SaSetup entr{"y" if len(named)==1 else "ies"}')

# Follow next-pointer chain from first named entry to last (next=0xffffff)
def follow_chain(start_entry, all_entries):
    """Follow relative next pointers; return ordered list of entries in chain."""
    chain = [start_entry]
    current = start_entry
    seen = {current['abs']}
    while current['next'] != NVRAM_NEXT_END:
        next_abs = current['abs'] + current['next']
        match = [e for e in all_entries if e['abs'] == next_abs]
        if not match:
            print(f'    WARNING: next pointer 0x{next_abs:x} not found in parsed entries')
            break
        nxt = match[0]
        if nxt['abs'] in seen:
            print(f'    WARNING: cycle detected in NVAR chain at 0x{nxt["abs"]:x}')
            break
        seen.add(nxt['abs'])
        chain.append(nxt)
        current = nxt
    return chain

chain = follow_chain(named[0], entries)
active = chain[-1]  # last in chain = current value

print(f'    Chain length: {len(chain)} entries')
for i, e in enumerate(chain):
    marker = ' ← ACTIVE' if e is active else ''
    print(f'      [{i}] abs=0x{e["abs"]:x} size={e["size"]} next=0x{e["next"]:06x} '
          f'data_only={e["is_data_only"]}{marker}')

# ── Step 4: locate DVMT byte within active entry ──────────────────────────────
print('[4] Locating DVMT byte...')
dvmt_abs = active['data_abs'] + IFR_VAR_OFFSET
current_val = flash[dvmt_abs]

data_len = active['abs'] + active['size'] - active['data_abs']
print(f'    Active entry abs:  0x{active["abs"]:x}')
print(f'    Data starts at:    abs 0x{active["data_abs"]:x}')
print(f'    Data length:       {data_len} bytes (SaSetup = 890 expected)')
print(f'    DVMT byte at:      abs 0x{dvmt_abs:x}  (SaSetup[0x{IFR_VAR_OFFSET:02x}])')
print(f'    Current value:     0x{current_val:02x}  (expected 0x{EXPECTED_OLD:02x})')

# Sanity checks
assert active['abs'] >= store_off and active['abs'] < store_off + store_sz, \
    'ACTIVE entry outside NVAR store bounds'
assert dvmt_abs >= store_off and dvmt_abs < store_off + store_sz, \
    'DVMT byte outside NVAR store bounds'
assert data_len == 890, \
    f'SaSetup data length {data_len} != 890 — wrong variable?'
assert flash[active['abs']:active['abs']+4] == NVAR_SIG, \
    'NVAR signature missing at active entry'
assert active['next'] == NVRAM_NEXT_END, \
    f'Active entry next=0x{active["next"]:x} != 0xffffff'

if current_val != EXPECTED_OLD:
    print(f'ERROR: DVMT byte is 0x{current_val:02x}, expected 0x{EXPECTED_OLD:02x} — aborting')
    sys.exit(1)

# ── Step 5: prepare patched sector ───────────────────────────────────────────
sector_start = (dvmt_abs // SECTOR_SIZE) * SECTOR_SIZE
off_in_sector = dvmt_abs - sector_start
sector = bytearray(flash[sector_start:sector_start + SECTOR_SIZE])
assert sector[off_in_sector] == EXPECTED_OLD, 'Sector byte mismatch'
patched = bytearray(sector)
patched[off_in_sector] = NEW_VALUE

diffs = [i for i in range(SECTOR_SIZE) if sector[i] != patched[i]]
assert len(diffs) == 1 and diffs[0] == off_in_sector

print()
print(f'    Sector:            0x{sector_start:x}–0x{sector_start+SECTOR_SIZE:x}')
print(f'    Byte in sector:    0x{off_in_sector:x}')
print(f'    Change:            0x{EXPECTED_OLD:02x} → 0x{NEW_VALUE:02x}  (64MB → 128MB)')
print(f'    Bytes changed:     {len(diffs)} (must be 1) ✓')
print()

# ── Step 6: dry run or write ──────────────────────────────────────────────────
if DRY_RUN:
    print('DRY RUN — all checks passed. Re-run with --write to apply.')
    print()
    print(f'Would erase+write sector 0x{sector_start:x} on {MTD_DEV}')
    sys.exit(0)

print('[5] Writing...')
fd = os.open(MTD_DEV, os.O_RDWR | os.O_SYNC)

# Re-verify from live fd (redundant but safe — confirms dump matches current state)
os.lseek(fd, dvmt_abs, os.SEEK_SET)
live_byte = os.read(fd, 1)[0]
if live_byte != EXPECTED_OLD:
    print(f'ERROR: live flash byte 0x{live_byte:02x} != expected 0x{EXPECTED_OLD:02x} '
          f'(flash changed since read?) — aborting')
    os.close(fd)
    sys.exit(1)
print(f'    Live flash byte confirmed: 0x{live_byte:02x} ✓')

erase_struct = struct.pack('II', sector_start, SECTOR_SIZE)
try:
    fcntl.ioctl(fd, MEMUNLOCK, erase_struct)
    print('    Sector unlocked')
except Exception as e:
    print(f'    Unlock skipped ({e})')

print(f'    Erasing sector 0x{sector_start:x}...')
fcntl.ioctl(fd, MEMERASE, erase_struct)
print('    Erase OK')

os.lseek(fd, sector_start, os.SEEK_SET)
written = os.write(fd, bytes(patched))
print(f'    Wrote {written} bytes')

# Verify
os.lseek(fd, dvmt_abs, os.SEEK_SET)
verified = os.read(fd, 1)[0]
os.close(fd)

if verified == NEW_VALUE:
    print(f'SUCCESS: DVMT = 0x{verified:02x} (128MB). Reboot to apply.')
else:
    print(f'FAIL: DVMT still 0x{verified:02x} — SPI write protection active, use RU.efi instead')
    sys.exit(1)
