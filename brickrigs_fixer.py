#!/usr/bin/env python3
"""
Brick Rigs WorkshopDL Fixer
============================
Reverse-engineered MetaData.brm format (confirmed from game-generated files):

  0x00        1 byte   0x11  (fixed marker)
  0x01-02     2 bytes  Title length marker: [256-title_len, 0xFF]
  0x03+       N*2      Title as UTF-16LE (NO null terminator)
  next 2      2 bytes  Desc length marker:  [256-desc_len, 0xFF]
  next D*2    D*2      Description as UTF-16LE (NO null terminator)
  next 2      2 bytes  uint16 LE  (= 1 in fresh files; game writes other values)
  next 20     5*4      5 x float32 LE  (bounding box, calculated by game)
  next 4      uint32   Unix timestamp  (always 0x6507091D in observed files)
  next 4      uint32   Unknown1
  next 4      uint32   Unknown2
  next 3      3 bytes  Padding (000000)
  next 8      int64    FDateTime created  (.NET ticks since 0001-01-01)
  next 8      int64    FDateTime modified
  next 1      uint8    Tag count
  next var    [len8+ASCII] Tags (1-byte length + ASCII bytes each)

SAFE TO MODIFY: title, description, tags
DO NOT TOUCH:   everything from uint16 onward (game recalculates on save)

KEY DISCOVERY: there is NO null terminator between strings or after description.
Strings are purely length-prefixed. Earlier versions of this script wrote null
terminators which shifted the entire binary section and caused "no bricks" errors.
"""

import struct
import os
import sys
import shutil
import json
import urllib.request
import urllib.parse
import datetime
from pathlib import Path


HEADER_MARKER = 0x11
DEFAULT_UINT16 = 1       # the uint16 field value in fresh game-created files
DEFAULT_UNIX_TS = 0x6507091D  # Sep 17 2023 - observed in all sample files


# ─────────────────────────────────────────────────────────────────────────────
# ENCODING / DECODING
# ─────────────────────────────────────────────────────────────────────────────

def encode_string(s: str) -> bytes:
    """
    Encode a string as: [256-len, 0xFF] + UTF-16LE chars (no null terminator).
    Max 254 chars. Empty string encoded as [0xFF, 0xFF] (length=1, space char).
    """
    s = s[:254]
    if not s:
        s = " "  # game doesn't support truly empty strings in this format
    marker = bytes([256 - len(s), 0xFF])
    return marker + s.encode('utf-16-le')


def decode_string(data: bytes, pos: int):
    """
    Decode a length-prefixed UTF-16LE string.
    Returns (string, new_pos).
    """
    if pos + 1 >= len(data):
        return "", pos + 2
    length = 256 - data[pos]   # marker byte -> char count
    pos += 2                   # skip marker
    end = pos + length * 2
    end = min(end, len(data))
    s = data[pos:end].decode('utf-16-le', errors='replace')
    return s, end


# ─────────────────────────────────────────────────────────────────────────────
# BrmMetaData class
# ─────────────────────────────────────────────────────────────────────────────

class BrmMetaData:

    def __init__(self):
        self.title = ""
        self.description = ""
        self.uint16_field = DEFAULT_UINT16
        self.floats = [0.0] * 5
        self.unix_ts = DEFAULT_UNIX_TS
        self.unknown1 = 0
        self.unknown2 = 0
        self.pad3 = b'\x00\x00\x00'
        self.fdatetime_created = 0
        self.fdatetime_modified = 0
        self.tags = ["None", "None", "None"]

    # ── read ──────────────────────────────────────────────────────────────────

    @classmethod
    def from_bytes(cls, data: bytes) -> "BrmMetaData":
        obj = cls()

        if not data or data[0] != HEADER_MARKER:
            raise ValueError(f"Not a MetaData.brm file (expected 0x11, got {data[0]:02x})")

        pos = 1
        obj.title, pos = decode_string(data, pos)
        obj.description, pos = decode_string(data, pos)

        # Binary section
        def safe_unpack(fmt, p):
            size = struct.calcsize(fmt)
            if p + size > len(data):
                return None, p
            return struct.unpack_from(fmt, data, p)[0], p + size

        val, pos = safe_unpack('<H', pos)
        obj.uint16_field = val if val is not None else DEFAULT_UINT16

        obj.floats = []
        for _ in range(5):
            val, pos = safe_unpack('<f', pos)
            obj.floats.append(val if val is not None else 0.0)

        val, pos = safe_unpack('<I', pos); obj.unix_ts   = val if val is not None else DEFAULT_UNIX_TS
        val, pos = safe_unpack('<I', pos); obj.unknown1  = val or 0
        val, pos = safe_unpack('<I', pos); obj.unknown2  = val or 0

        obj.pad3 = data[pos:pos+3] if pos + 3 <= len(data) else b'\x00\x00\x00'
        pos = min(pos + 3, len(data))

        val, pos = safe_unpack('<q', pos); obj.fdatetime_created  = val or 0
        val, pos = safe_unpack('<q', pos); obj.fdatetime_modified = val or 0

        # Tags
        obj.tags = []
        if pos < len(data):
            tag_count = data[pos]; pos += 1
            for _ in range(tag_count):
                if pos >= len(data): break
                slen = data[pos]; pos += 1
                if pos + slen > len(data):
                    obj.tags.append(data[pos:].decode('ascii', errors='replace'))
                    break
                obj.tags.append(data[pos:pos+slen].decode('ascii', errors='replace'))
                pos += slen

        return obj

    @classmethod
    def from_file(cls, path) -> "BrmMetaData":
        return cls.from_bytes(Path(path).read_bytes())

    # ── write ─────────────────────────────────────────────────────────────────

    def to_bytes(self) -> bytes:
        buf = bytearray()
        buf += bytes([HEADER_MARKER])
        buf += encode_string(self.title)
        buf += encode_string(self.description)
        buf += struct.pack('<H', self.uint16_field)
        for f in self.floats:
            buf += struct.pack('<f', f)
        buf += struct.pack('<I', self.unix_ts)
        buf += struct.pack('<I', self.unknown1)
        buf += struct.pack('<I', self.unknown2)
        buf += self.pad3
        buf += struct.pack('<q', self.fdatetime_created)
        buf += struct.pack('<q', self.fdatetime_modified)
        buf += bytes([len(self.tags)])
        for tag in self.tags:
            tag_bytes = tag.encode('ascii', errors='replace')
            buf += bytes([len(tag_bytes)]) + tag_bytes
        return bytes(buf)

    def save(self, path):
        Path(path).write_bytes(self.to_bytes())

    # ── helpers ───────────────────────────────────────────────────────────────

    def created_datetime(self):
        return _ticks_to_dt(self.fdatetime_created)

    def modified_datetime(self):
        return _ticks_to_dt(self.fdatetime_modified)

    def __repr__(self):
        return (
            f"BrmMetaData(\n"
            f"  title={self.title!r}\n"
            f"  description={self.description!r}\n"
            f"  uint16={self.uint16_field}\n"
            f"  floats={[round(f,2) for f in self.floats]}\n"
            f"  unix_ts={self.unix_ts} ({datetime.datetime.fromtimestamp(self.unix_ts) if self.unix_ts else 'N/A'})\n"
            f"  created={self.created_datetime()}\n"
            f"  modified={self.modified_datetime()}\n"
            f"  tags={self.tags}\n"
            f")"
        )


def _ticks_to_dt(ticks: int):
    try:
        if ticks <= 0: return None
        return datetime.datetime(1,1,1) + datetime.timedelta(microseconds=ticks//10)
    except (OverflowError, ValueError):
        return None

def _dt_to_ticks(dt: datetime.datetime) -> int:
    return int((dt - datetime.datetime(1,1,1)).total_seconds() * 1e7)


# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATE GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

def make_clean_metadata(title: str, description: str = "", tags=None) -> BrmMetaData:
    """Generate a clean MetaData.brm identical in structure to game-created files."""
    meta = BrmMetaData()
    meta.title = title
    meta.description = description
    meta.uint16_field = DEFAULT_UINT16
    meta.floats = [0.0] * 5        # game calculates these on first spawn
    meta.unix_ts = DEFAULT_UNIX_TS
    meta.unknown1 = 0x18951961     # preserved from observed files
    meta.unknown2 = 0x00504260     # preserved from observed files
    meta.pad3 = b'\x00\x00\x00'
    now = _dt_to_ticks(datetime.datetime.now())
    meta.fdatetime_created = now
    meta.fdatetime_modified = now
    meta.tags = tags if tags else ["None", "None", "None"]
    return meta


# ─────────────────────────────────────────────────────────────────────────────
# STEAM WORKSHOP API
# ─────────────────────────────────────────────────────────────────────────────

STEAM_API_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"

def fetch_workshop_info(workshop_ids: list) -> dict:
    """Fetch title + preview_url for Workshop IDs. No API key needed."""
    if not workshop_ids:
        return {}
    post_data = {"itemcount": len(workshop_ids)}
    for i, wid in enumerate(workshop_ids):
        post_data[f"publishedfileids[{i}]"] = str(wid)
    encoded = urllib.parse.urlencode(post_data).encode('utf-8')
    req = urllib.request.Request(STEAM_API_URL, data=encoded, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"  [WARN] Steam API error: {e}")
        return {}
    items = result.get('response', {}).get('publishedfiledetails', [])
    return {
        str(item.get('publishedfileid','')): {
            'title': item.get('title',''),
            'preview_url': item.get('preview_url',''),
        }
        for item in items
    }

def download_preview(url: str, dest_path: str) -> bool:
    if not url:
        return False
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            Path(dest_path).write_bytes(resp.read())
        return True
    except Exception as e:
        print(f"  [WARN] Preview download failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# CORE FIX FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def fix_build_folder(folder_path: Path, title: str, preview_url: str = "",
                     rename_folder: bool = True):
    """Fix a single build folder: patch/regenerate MetaData.brm, download preview."""
    brm_path = folder_path / "MetaData.brm"
    preview_path = folder_path / "Preview.png"
    safe_title = title[:254]

    # Always regenerate clean - never try to patch old/unknown format files
    meta = make_clean_metadata(safe_title)
    meta.save(brm_path)
    print(f"  [OK] MetaData.brm -> {safe_title!r}")

    if preview_url and not preview_path.exists():
        if download_preview(preview_url, str(preview_path)):
            print(f"  [OK] Preview.png downloaded")
    elif preview_path.exists():
        print(f"  [  ] Preview.png already exists")

    new_path = folder_path
    if rename_folder:
        safe_name = _sanitize_name(title)
        if safe_name and safe_name != folder_path.name:
            candidate = folder_path.parent / safe_name
            counter = 1
            while candidate.exists():
                candidate = folder_path.parent / f"{safe_name}_{counter}"
                counter += 1
            folder_path.rename(candidate)
            new_path = candidate
            print(f"  [OK] Renamed: {folder_path.name!r} -> {candidate.name!r}")
    return new_path


def _sanitize_name(title: str) -> str:
    invalid = r'\/:*?"<>|'
    name = ''.join('_' if c in invalid else c for c in title).strip('. ')[:80]
    return name or "Unnamed"


# ─────────────────────────────────────────────────────────────────────────────
# MODES
# ─────────────────────────────────────────────────────────────────────────────

def mode_fix_workshop(builds_dir: str, rename: bool = True, dry_run: bool = False):
    """Fix all numeric (Workshop ID) folders using Steam API for names."""
    print(f"\n=== Fix Workshop folders in: {builds_dir} ===\n")
    folders = {
        e.name: e for e in Path(builds_dir).iterdir()
        if e.is_dir() and e.name.isdigit()
    }
    if not folders:
        print("No numeric Workshop ID folders found.")
        return

    print(f"Found {len(folders)} Workshop folders. Fetching from Steam...")
    info = fetch_workshop_info(list(folders.keys()))

    for wid, folder_path in folders.items():
        item = info.get(wid, {})
        title = item.get('title') or f"Workshop_{wid}"
        preview_url = item.get('preview_url', '')
        print(f"\n[{wid}] -> {title!r}")
        if dry_run:
            print(f"  [DRY RUN]")
        else:
            fix_build_folder(folder_path, title, preview_url, rename_folder=rename)

    print("\n=== Done ===")


def mode_fix_all(builds_dir: str, skip: str = None, dry_run: bool = False):
    """Fix all folders using folder name as title."""
    print(f"\n=== Fix all folders in: {builds_dir} ===\n")
    for entry in sorted(Path(builds_dir).iterdir()):
        if not entry.is_dir():
            continue
        if skip and entry.name == skip:
            print(f"[SKIP] {entry.name}")
            continue
        print(f"[{entry.name}]")
        if dry_run:
            print(f"  [DRY RUN] title={entry.name!r}")
        else:
            try:
                fix_build_folder(entry, entry.name, rename_folder=False)
            except Exception as e:
                print(f"  [ERROR] {e}")
    print("\n=== Done ===")


def mode_inspect(brm_path: str):
    """Print contents of a MetaData.brm file."""
    try:
        meta = BrmMetaData.from_file(brm_path)
        print(f"\n=== {brm_path} ===")
        print(meta)
    except Exception as e:
        data = Path(brm_path).read_bytes()
        print(f"\nFailed to parse: {e}")
        print(f"Header bytes: {data[:3].hex()}")
        print(f"File size: {len(data)} bytes")


def mode_patch(brm_path: str, title: str, out: str = None):
    """Patch title in a single file (regenerates clean file)."""
    out = out or brm_path
    meta = make_clean_metadata(title)
    # Try to preserve binary fields from original if parseable
    try:
        orig = BrmMetaData.from_file(brm_path)
        meta.uint16_field = orig.uint16_field
        meta.floats = orig.floats
        meta.unix_ts = orig.unix_ts
        meta.unknown1 = orig.unknown1
        meta.unknown2 = orig.unknown2
        meta.pad3 = orig.pad3
        meta.fdatetime_created = orig.fdatetime_created
        meta.tags = orig.tags
        print(f"  Preserved binary fields from original")
    except Exception as e:
        print(f"  Could not parse original ({e}), using defaults")
    meta.save(out)
    print(f"  Saved: {out!r}  title={title!r}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Brick Rigs WorkshopDL Fixer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python brickrigs_fixer.py fix-workshop --dir "C:/BrickRigs/Vehicles"
  python brickrigs_fixer.py fix-all      --dir "C:/BrickRigs/Vehicles" --skip "_cache"
  python brickrigs_fixer.py inspect      --file "MetaData.brm"
  python brickrigs_fixer.py patch        --file "MetaData.brm" --title "My Build"
""")
    sub = parser.add_subparsers(dest='cmd')

    p1 = sub.add_parser('fix-workshop')
    p1.add_argument('--dir', required=True)
    p1.add_argument('--no-rename', action='store_true')
    p1.add_argument('--dry-run', action='store_true')

    p2 = sub.add_parser('fix-all')
    p2.add_argument('--dir', required=True)
    p2.add_argument('--skip', default=None)
    p2.add_argument('--dry-run', action='store_true')

    p3 = sub.add_parser('inspect')
    p3.add_argument('--file', required=True)

    p4 = sub.add_parser('patch')
    p4.add_argument('--file', required=True)
    p4.add_argument('--title', required=True)
    p4.add_argument('--out', default=None)

    args = parser.parse_args()

    if args.cmd == 'fix-workshop':
        mode_fix_workshop(args.dir, rename=not args.no_rename, dry_run=args.dry_run)
    elif args.cmd == 'fix-all':
        mode_fix_all(args.dir, skip=args.skip, dry_run=args.dry_run)
    elif args.cmd == 'inspect':
        mode_inspect(args.file)
    elif args.cmd == 'patch':
        mode_patch(args.file, args.title, args.out)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
