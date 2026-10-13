"""Install portable FFmpeg tools into this application's accessible workspace."""
from __future__ import annotations

import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BIN = ROOT / "work" / "tools-v2" / "ffmpeg" / "bin"
CACHE = ROOT / "work" / "tools-v2" / "cache"
ARCHIVE = CACHE / "ffmpeg-n9.0-latest-win64-gpl-9.0.zip"
URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n9.0-latest-win64-gpl-9.0.zip"


def executable_ok(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        result = subprocess.run([str(path), "-version"], capture_output=True, timeout=15)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


BIN.mkdir(parents=True, exist_ok=True)
CACHE.mkdir(parents=True, exist_ok=True)
if all(executable_ok(BIN / name) for name in ("ffmpeg.exe", "ffprobe.exe")):
    print(f"FFmpeg ve FFprobe hazır: {BIN}")
    raise SystemExit(0)

# Download directly: this avoids broken/locked ffmpeg-downloader package trees.
if not ARCHIVE.is_file() or ARCHIVE.stat().st_size < 100_000_000:
    partial = ARCHIVE.with_suffix(ARCHIVE.suffix + ".part")
    request = urllib.request.Request(URL, headers={"User-Agent": "ClipAtolye/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out, length=1024 * 1024)
        partial.replace(ARCHIVE)
    except Exception:
        partial.unlink(missing_ok=True)
        raise

with zipfile.ZipFile(ARCHIVE) as bundle:
    members = [
        item for item in bundle.infolist()
        if "/bin/" in item.filename.replace("\\", "/")
        and not item.is_dir()
    ]
    for item in members:
        normalized = item.filename.replace("\\", "/")
        relative = normalized.split("/bin/", 1)[1]
        # Keep only FFmpeg's bin contents (EXEs and any adjacent runtime DLLs).
        if "/" in relative or not relative:
            continue
        if not relative.lower().endswith((".exe", ".dll")):
            continue
        destination = BIN / Path(relative).name
        with bundle.open(item) as src, destination.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)

missing = [name for name in ("ffmpeg.exe", "ffprobe.exe") if not executable_ok(BIN / name)]
if missing:
    raise SystemExit("FFmpeg arşivinden çalışır dosyalar çıkarılamadı: " + ", ".join(missing))
print(f"FFmpeg ve FFprobe hazır: {BIN}")
