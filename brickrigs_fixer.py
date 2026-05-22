#!/usr/bin/env python3
"""
Brick Rigs WorkshopDL Fixer
============================
Fixes builds downloaded via WorkshopDL:
  - Patches MetaData.brm (title + description)
  - Downloads Preview.png from Steam Workshop
  - Renames folders to human-readable names
  - Fetches build name from Steam Workshop API

MetaData.brm Format (reverse-engineered):
==========================================
Offset  Size  Type              Field
------  ----  ----              -----
0x00     3    bytes             HEADER = 11 CF FF
0x03     var  UTF-16LE + \\0    TITLE  (variable length)
var      var  UTF-16LE + \\0    DESCRIPTION / AUTHOR (second string)
var      2    uint16 LE         UNKNOWN_FLAGS (always = 8)
var      4    float32 LE        DIM_0  (bounding box / spawn data)
var      4    float32 LE        DIM_1
var      4    float32 LE        DIM_2
var      4    float32 LE        DIM_3
var      4    float32 LE        DIM_4  (brick count?)
var      4    uint32 LE         UNIX_TS (workshop upload date or similar)
var      4    uint32 LE         UNKNOWN1
var      4    uint32 LE         UNKNOWN2
var      3    bytes             PAD (000000)
var      8    int64 LE          FDATETIME_CREATED  (.NET/UE ticks since 0001-01-01)
var      8    int64 LE          FDATETIME_MODIFIED
var      1    uint8             TAG_COUNT
var      var  [len8 + ASCII]    TAGS  (each: 1-byte length + ASCII string)

SAFE TO MODIFY: TITLE, DESCRIPTION, TAGS
DO NOT TOUCH:   everything else (game recalculates bounding box / timestamps on save)
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


HEADER = bytes([0x11, 0xCF, 0xFF])


# ─────────────────────────────────────────────────────────────────────────────
# LOW-LEVEL: parser / serializer
# ─────────────────────────────────────────────────────────────────────────────

class BrmMetaData:
    """Parser and serializer for MetaData.brm."""

    def __init__(self):
        self.title = ""
        self.description = ""
        self.unknown_flags = 8
        self.floats = []         # 5 float32 values
        self.unix_ts = 0         # uint32
        self.unknown1 = 0        # uint32
        self.unknown2 = 0        # uint32
        self.pad3 = b'\x00\x00\x00'  # 3 bytes padding
        self.fdatetime_created = 0   # int64
        self.fdatetime_modified = 0  # int64
        self.tags = []           # list of str

    # ── read ──────────────────────────────────────────────────────────────────

    @classmethod
    def from_bytes(cls, data: bytes) -> "BrmMetaData":
        obj = cls()
        pos = 0

        # Header
        if data[:3] != HEADER:
            raise ValueError(f"Bad header: {data[:3].hex()} (expected 11cfff)")
        pos = 3

        # String 1: TITLE
        obj.title, pos = _read_utf16_null(data, pos)

        # String 2: DESCRIPTION / AUTHOR
        obj.description, pos = _read_utf16_null(data, pos)

        def safe_unpack(fmt, offset):
            size = struct.calcsize(fmt)
            if offset + size > len(data):
                return None, offset
            return struct.unpack_from(fmt, data, offset)[0], offset + size

        # uint16 flags
        val, pos = safe_unpack('<H', pos)
        obj.unknown_flags = val if val is not None else 8

        # 5 floats
        obj.floats = []
        for _ in range(5):
            val, pos = safe_unpack('<f', pos)
            obj.floats.append(val if val is not None else 0.0)

        # uint32 unix ts + unknown x2
        val, pos = safe_unpack('<I', pos); obj.unix_ts   = val or 0
        val, pos = safe_unpack('<I', pos); obj.unknown1  = val or 0
        val, pos = safe_unpack('<I', pos); obj.unknown2  = val or 0

        # 3 bytes padding
        obj.pad3 = data[pos:pos+3] if pos + 3 <= len(data) else b'\x00\x00\x00'
        pos = min(pos + 3, len(data))

        # FDateTime x2 (int64)
        val, pos = safe_unpack('<q', pos); obj.fdatetime_created  = val or 0
        val, pos = safe_unpack('<q', pos); obj.fdatetime_modified = val or 0

        # Tags
        obj.tags = []
        if pos < len(data):
            tag_count = data[pos]
            pos += 1
            for _ in range(tag_count):
                if pos >= len(data):
                    break
                slen = data[pos]
                pos += 1
                if pos + slen > len(data):
                    obj.tags.append(data[pos:].decode('ascii', errors='replace'))
                    pos = len(data)
                    break
                obj.tags.append(data[pos:pos+slen].decode('ascii', errors='replace'))
                pos += slen

        if pos != len(data):
            print(f"  [WARN] Parsed {pos} bytes but file is {len(data)} bytes")

        return obj

    @classmethod
    def from_file(cls, path) -> "BrmMetaData":
        return cls.from_bytes(Path(path).read_bytes())

    # ── write ─────────────────────────────────────────────────────────────────

    def to_bytes(self) -> bytes:
        buf = bytearray()

        buf += HEADER

        buf += _encode_utf16_null(self.title)
        buf += _encode_utf16_null(self.description)

        buf += struct.pack('<H', self.unknown_flags)

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
        """Return created time as Python datetime (may be None if invalid)."""
        return _fdatetime_to_python(self.fdatetime_created)

    def modified_datetime(self):
        return _fdatetime_to_python(self.fdatetime_modified)

    def __repr__(self):
        return (
            f"BrmMetaData(\n"
            f"  title={self.title!r}\n"
            f"  description={self.description!r}\n"
            f"  flags={self.unknown_flags}\n"
            f"  floats={[round(f, 2) for f in self.floats]}\n"
            f"  unix_ts={self.unix_ts} ({datetime.datetime.fromtimestamp(self.unix_ts) if self.unix_ts else 'N/A'})\n"
            f"  created={self.created_datetime()}\n"
            f"  modified={self.modified_datetime()}\n"
            f"  tags={self.tags}\n"
            f")"
        )


def _read_utf16_null(data: bytes, pos: int):
    """Read UTF-16LE null-terminated string. Returns (string, new_pos)."""
    chars = []
    while pos + 1 < len(data):
        code = data[pos] | (data[pos + 1] << 8)
        pos += 2
        if code == 0:
            break
        chars.append(chr(code))
    return ''.join(chars), pos


def _encode_utf16_null(s: str) -> bytes:
    """Encode string as UTF-16LE with null terminator."""
    return s.encode('utf-16-le') + b'\x00\x00'


def _fdatetime_to_python(ticks: int):
    """Convert .NET/UE FDateTime ticks (100ns since 0001-01-01) to datetime."""
    try:
        if ticks <= 0:
            return None
        return datetime.datetime(1, 1, 1) + datetime.timedelta(microseconds=ticks // 10)
    except (OverflowError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATE: generate a clean "blank" MetaData.brm for new builds
# ─────────────────────────────────────────────────────────────────────────────

def make_template_metadata(title: str, description: str = "", tags=None) -> BrmMetaData:
    """
    Generate a clean MetaData.brm for a build.
    The binary fields (floats, timestamps) are copied from a known-good default
    so the game accepts the file without recalculating everything.
    The game will overwrite these when the build is first loaded/saved in-game.
    """
    meta = BrmMetaData()
    meta.title = title
    meta.description = description
    meta.unknown_flags = 8

    # Default neutral values (game will overwrite on first save)
    meta.floats = [0.0, 0.0, 0.0, 0.0, 0.0]

    now_ticks = _python_to_fdatetime(datetime.datetime.now())
    meta.unix_ts = int(datetime.datetime.now().timestamp())
    meta.unknown1 = 0
    meta.unknown2 = 0
    meta.pad3 = b'\x00\x00\x00'
    meta.fdatetime_created = now_ticks
    meta.fdatetime_modified = now_ticks

    meta.tags = tags or ["None", "None", "None"]

    return meta


def _python_to_fdatetime(dt: datetime.datetime) -> int:
    """Convert Python datetime to .NET/UE FDateTime ticks."""
    epoch = datetime.datetime(1, 1, 1)
    delta = dt - epoch
    return int(delta.total_seconds() * 1e7)


# ─────────────────────────────────────────────────────────────────────────────
# PATCHING: modify existing MetaData.brm
# ─────────────────────────────────────────────────────────────────────────────

def patch_metadata_title(src_path, dst_path, new_title: str, new_description: str = None):
    """
    Load an existing MetaData.brm, update title (and optionally description),
    save to dst_path. All binary fields are preserved intact.

    This is the SAFE way to patch — no binary offsets touched manually.
    """
    meta = BrmMetaData.from_file(src_path)
    meta.title = new_title
    if new_description is not None:
        meta.description = new_description
    meta.save(dst_path)
    print(f"  [PATCH] {src_path} -> {dst_path}")
    print(f"          title={new_title!r}, desc={meta.description!r}")


# ─────────────────────────────────────────────────────────────────────────────
# STEAM WORKSHOP API
# ─────────────────────────────────────────────────────────────────────────────

STEAM_API_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
APP_ID = "552100"  # Brick Rigs App ID


def fetch_workshop_info(workshop_ids: list) -> dict:
    """
    Fetch title + preview_url for a list of Workshop IDs.
    Returns dict: {workshop_id_str: {"title": ..., "preview_url": ...}}
    No API key needed for this endpoint.
    """
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
    out = {}
    for item in items:
        wid = str(item.get('publishedfileid', ''))
        out[wid] = {
            'title': item.get('title', ''),
            'preview_url': item.get('preview_url', ''),
            'description': item.get('description', ''),
        }
    return out


def download_preview(url: str, dest_path: str) -> bool:
    """Download preview image to dest_path. Returns True on success."""
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
# WORKSHOPDL FIXER
# ─────────────────────────────────────────────────────────────────────────────

def is_workshop_id_folder(name: str) -> bool:
    """Return True if folder name is a pure numeric Workshop ID."""
    return name.isdigit()


def find_workshop_folders(builds_dir: str) -> dict:
    """
    Scan builds directory.
    Returns {workshop_id: folder_path} for all numeric-named folders.
    """
    result = {}
    for entry in Path(builds_dir).iterdir():
        if entry.is_dir() and is_workshop_id_folder(entry.name):
            result[entry.name] = entry
    return result


def fix_workshop_build(folder_path: Path, title: str, preview_url: str = "",
                       template_meta_path: str = None, rename_folder: bool = True):
    """
    Fix a single WorkshopDL build folder:
    1. Patch or create MetaData.brm with correct title
    2. Download Preview.png if URL provided
    3. Optionally rename folder to sanitized title
    Returns new folder path (may be renamed).
    """
    brm_path = folder_path / "MetaData.brm"
    preview_path = folder_path / "Preview.png"

    # ── Patch MetaData.brm ──
    safe_title = title[:100]  # Brick Rigs title limit is generous but let's be safe

    if brm_path.exists():
        # Patch existing file - preserve all binary fields
        meta = BrmMetaData.from_file(brm_path)
        meta.title = safe_title
        # Optionally clear the "description" field (second string) to avoid confusion
        # Keep it as-is if you want to preserve the original author tag
        meta.save(brm_path)
        print(f"  [OK] Patched MetaData.brm: {safe_title!r}")
    elif template_meta_path and Path(template_meta_path).exists():
        # Copy template and patch
        shutil.copy(template_meta_path, brm_path)
        meta = BrmMetaData.from_file(brm_path)
        meta.title = safe_title
        meta.save(brm_path)
        print(f"  [OK] Created MetaData.brm from template: {safe_title!r}")
    else:
        # Generate from scratch
        meta = make_template_metadata(safe_title)
        meta.save(brm_path)
        print(f"  [OK] Generated new MetaData.brm: {safe_title!r}")

    # ── Download Preview ──
    if preview_url and not preview_path.exists():
        ok = download_preview(preview_url, str(preview_path))
        if ok:
            print(f"  [OK] Downloaded Preview.png")
    elif preview_path.exists():
        print(f"  [  ] Preview.png already exists")

    # ── Rename folder ──
    new_path = folder_path
    if rename_folder:
        safe_name = _sanitize_folder_name(title)
        if safe_name and safe_name != folder_path.name:
            new_path = folder_path.parent / safe_name
            # Avoid collision
            counter = 1
            while new_path.exists():
                new_path = folder_path.parent / f"{safe_name}_{counter}"
                counter += 1
            folder_path.rename(new_path)
            print(f"  [OK] Renamed: {folder_path.name} -> {new_path.name}")

    return new_path


def _sanitize_folder_name(title: str) -> str:
    """Convert title to a valid folder name."""
    invalid = r'\/:*?"<>|'
    name = ''.join(c if c not in invalid else '_' for c in title)
    name = name.strip('. ')[:80]
    return name or "Unnamed"


# ─────────────────────────────────────────────────────────────────────────────
# MAIN MODES
# ─────────────────────────────────────────────────────────────────────────────

def mode_fix_workshop(builds_dir: str, template_path: str = None,
                      rename: bool = True, dry_run: bool = False):
    """
    MODE 1: Fix all numeric (Workshop ID) folders.
    Fetches names from Steam Workshop API, patches MetaData.brm, downloads previews.
    """
    print(f"\n=== MODE: Fix Workshop ID folders in {builds_dir} ===")
    folders = find_workshop_folders(builds_dir)
    if not folders:
        print("  No numeric Workshop ID folders found.")
        return

    print(f"  Found {len(folders)} Workshop ID folders: {list(folders.keys())}")

    # Fetch info from Steam
    print("  Fetching from Steam Workshop API...")
    info = fetch_workshop_info(list(folders.keys()))

    for wid, folder_path in folders.items():
        print(f"\n[{wid}] {folder_path.name}")
        item = info.get(wid, {})
        title = item.get('title') or f"Workshop_{wid}"
        preview_url = item.get('preview_url', '')

        if not title:
            print(f"  [WARN] No title from Steam, using ID as fallback")
            title = f"Workshop_{wid}"

        if dry_run:
            print(f"  [DRY RUN] Would patch title={title!r}, preview={bool(preview_url)}")
        else:
            fix_workshop_build(folder_path, title, preview_url,
                               template_meta_path=template_path,
                               rename_folder=rename)

    print("\n=== Done ===")


def mode_fix_all(builds_dir: str, skip_folder: str = None,
                 template_path: str = None, dry_run: bool = False):
    """
    MODE 2: Fix all folders using folder name as title.
    Useful if you already renamed folders or for non-Workshop builds.
    """
    print(f"\n=== MODE: Fix all folders in {builds_dir} (use folder name as title) ===")

    for entry in Path(builds_dir).iterdir():
        if not entry.is_dir():
            continue
        if skip_folder and entry.name == skip_folder:
            print(f"  [SKIP] {entry.name} (skip_folder)")
            continue

        title = entry.name
        brm_path = entry / "MetaData.brm"

        print(f"\n[{entry.name}]")
        if dry_run:
            print(f"  [DRY RUN] Would set title={title!r}")
            continue

        try:
            if brm_path.exists():
                meta = BrmMetaData.from_file(brm_path)
                meta.title = title[:100]
                meta.save(brm_path)
                print(f"  [OK] Patched title={title!r}")
            elif template_path:
                shutil.copy(template_path, brm_path)
                meta = BrmMetaData.from_file(brm_path)
                meta.title = title[:100]
                meta.save(brm_path)
                print(f"  [OK] Created from template, title={title!r}")
            else:
                meta = make_template_metadata(title)
                meta.save(brm_path)
                print(f"  [OK] Generated MetaData.brm, title={title!r}")
        except Exception as e:
            print(f"  [SKIP] Error: {e}")

    print("\n=== Done ===")


def mode_inspect(brm_path: str):
    """Inspect and print a MetaData.brm file."""
    meta = BrmMetaData.from_file(brm_path)
    print(f"\n=== {brm_path} ===")
    print(meta)


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
  # Fix all Workshop ID folders (fetches names from Steam):
  python brickrigs_fixer.py fix-workshop --dir "C:/BrickRigs/Vehicles"

  # Fix all folders using folder name as title:
  python brickrigs_fixer.py fix-all --dir "C:/BrickRigs/Vehicles" --skip "_template"

  # Inspect a MetaData.brm:
  python brickrigs_fixer.py inspect --file "C:/BrickRigs/Vehicles/MyBuild/MetaData.brm"

  # Patch a single file's title:
  python brickrigs_fixer.py patch --file "MetaData.brm" --title "My Cool Build"
""")

    sub = parser.add_subparsers(dest='cmd')

    # fix-workshop
    p1 = sub.add_parser('fix-workshop', help='Fix numeric Workshop ID folders')
    p1.add_argument('--dir', required=True, help='Builds directory')
    p1.add_argument('--template', help='Path to a known-good MetaData.brm template')
    p1.add_argument('--no-rename', action='store_true', help='Do not rename folders')
    p1.add_argument('--dry-run', action='store_true')

    # fix-all
    p2 = sub.add_parser('fix-all', help='Fix all folders using folder name as title')
    p2.add_argument('--dir', required=True, help='Builds directory')
    p2.add_argument('--skip', help='Folder name to skip (e.g. _template)')
    p2.add_argument('--template', help='Path to a known-good MetaData.brm template')
    p2.add_argument('--dry-run', action='store_true')

    # inspect
    p3 = sub.add_parser('inspect', help='Inspect a MetaData.brm')
    p3.add_argument('--file', required=True)

    # patch
    p4 = sub.add_parser('patch', help='Patch title in a single MetaData.brm')
    p4.add_argument('--file', required=True)
    p4.add_argument('--title', required=True)
    p4.add_argument('--desc', default=None, help='New description/author field')
    p4.add_argument('--out', help='Output path (default: overwrite in place)')

    args = parser.parse_args()

    if args.cmd == 'fix-workshop':
        mode_fix_workshop(
            args.dir,
            template_path=args.template,
            rename=not args.no_rename,
            dry_run=args.dry_run,
        )
    elif args.cmd == 'fix-all':
        mode_fix_all(
            args.dir,
            skip_folder=args.skip,
            template_path=args.template,
            dry_run=args.dry_run,
        )
    elif args.cmd == 'inspect':
        mode_inspect(args.file)
    elif args.cmd == 'patch':
        out = args.out or args.file
        patch_metadata_title(args.file, out, args.title, args.desc)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
