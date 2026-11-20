# ------------------------------------------------------------------------------
# Purpose:       Cross-platform MuseScore CLI discovery and content-hashed
#                MusicXML export / caching.
# ------------------------------------------------------------------------------
"""MuseScore CLI discovery and MusicXML export utilities."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import music21 as m21


MUSESCORE_EXTENSIONS = frozenset({".mscz", ".mscx"})
MUSICXML_EXTENSIONS = frozenset({".musicxml", ".xml", ".mxl"})


def find_musescore_binary() -> Optional[str]:
    """Find available MuseScore executable across Linux, WSL, macOS, and Windows."""
    # 0. Explicit environment override
    env_bin = os.environ.get("MUSESCORE_BIN")
    if env_bin and Path(env_bin).is_file():
        return env_bin

    # 1. Search PATH and ~/.local/bin
    for name in ("mscore", "musescore", "musescore4", "musescore3"):
        found = shutil.which(name)
        if found:
            return found

    user_local = Path.home() / ".local" / "bin" / "mscore"
    if user_local.is_file() and os.access(user_local, os.X_OK):
        return str(user_local)

    # 2. Windows / WSL standard install paths
    win_paths = [
        Path("/mnt/c/Program Files/MuseScore 4/bin/MuseScore4.exe"),
        Path("/mnt/c/Program Files/MuseScore 3/bin/MuseScore3.exe"),
        Path("C:/Program Files/MuseScore 4/bin/MuseScore4.exe"),
        Path("C:/Program Files/MuseScore 3/bin/MuseScore3.exe"),
    ]
    for wp in win_paths:
        if wp.is_file():
            return str(wp)

    # 3. macOS standard application bundles
    mac_paths = [
        Path("/Applications/MuseScore 4.app/Contents/MacOS/mscore"),
        Path("/Applications/MuseScore 3.app/Contents/MacOS/mscore"),
    ]
    for mp in mac_paths:
        if mp.is_file():
            return str(mp)

    return None


def configure_music21_musescore(musescore_bin: Optional[str] = None) -> Optional[str]:
    """Configures music21 to use the detected MuseScore executable for PDF rendering."""
    binary = musescore_bin or find_musescore_binary()
    if binary:
        env = m21.environment.Environment()
        env["musescoreDirectPNGPath"] = binary
        env["musicxmlPath"] = binary
    return binary


def _to_cli_path(file_path: Path, is_win_binary: bool) -> str:
    """Converts Linux path to Windows format if running a Windows binary under WSL."""
    abs_str = str(file_path.resolve())
    if is_win_binary and abs_str.startswith("/") and shutil.which("wslpath"):
        res = subprocess.run(
            ["wslpath", "-w", abs_str], capture_output=True, text=True, check=True
        )
        return res.stdout.strip()
    return abs_str


def _file_sha256_prefix(file_path: Path, length: int = 12) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:length]


def export_musicxml(
    score_path: Path | str,
    output_path: Optional[Path | str] = None,
    musescore_bin: Optional[str] = None,
) -> Path:
    """Exports `.mscz` / `.mscx` to standard MusicXML using the MuseScore CLI."""
    src = Path(score_path)
    if not src.is_file():
        raise FileNotFoundError(f"Input score file not found: {src}")

    out = src.with_suffix(".musicxml") if output_path is None else Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    binary = musescore_bin or find_musescore_binary()
    if not binary:
        raise RuntimeError(
            "MuseScore CLI binary not found. Please install MuseScore or set MUSESCORE_BIN."
        )

    is_win_exe = binary.lower().endswith(".exe")
    in_arg = _to_cli_path(src, is_win_exe)
    out_arg = _to_cli_path(out, is_win_exe)

    cmd = [binary, "-o", out_arg, in_arg]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0 or not out.is_file():
        err_msg = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"Process exited with {result.returncode}"
        )
        raise RuntimeError(f"MuseScore conversion failed: {err_msg}")

    return out


def resolve_to_musicxml(
    score_path: Path | str,
    cache_dir: Optional[Path | str] = None,
    musescore_bin: Optional[str] = None,
) -> Path:
    """Returns a MusicXML path for `.mscz`/`.mscx`/`.musicxml`/`.xml`/`.mxl` inputs.

    Uses SHA-256 content-hashed filenames in `cache_dir` so files with identical
    stems in different directories never collide in the cache.
    """
    src = Path(score_path)
    if not src.is_file():
        raise FileNotFoundError(f"Score file not found: {src}")

    suffix = src.suffix.lower()
    if suffix in MUSICXML_EXTENSIONS:
        return src

    if suffix in MUSESCORE_EXTENSIONS:
        cdir = Path(cache_dir) if cache_dir is not None else Path.home() / ".cache" / "musicdiff" / "musicxml"
        cdir.mkdir(parents=True, exist_ok=True)
        digest = _file_sha256_prefix(src)
        xml_path = cdir / f"{src.stem}_{digest}.musicxml"
        if not xml_path.is_file():
            export_musicxml(src, xml_path, musescore_bin=musescore_bin)
        return xml_path

    # Allow other music21-supported formats (e.g., .mei, .krn, .mid) to pass through
    return src
