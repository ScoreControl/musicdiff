# ------------------------------------------------------------------------------
# Purpose:       MuseScore audiosettings.json diffing (soundfonts, presets,
#                mixer levels, FX, master/aux buses).
# ------------------------------------------------------------------------------
"""Diffing utilities for MuseScore's embedded `audiosettings.json`."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from musicdiff.musescore.archive import MuseScoreArchive
from musicdiff.musescore.exporter import MUSESCORE_EXTENSIONS


def diff_json_values(
    val1: Any, val2: Any, prefix: str = ""
) -> List[Tuple[str, Any, Any]]:
    """Recursively compares two JSON values and returns `(path, old_val, new_val)` tuples."""
    if val1 == val2:
        return []

    if isinstance(val1, dict) and isinstance(val2, dict):
        diffs: List[Tuple[str, Any, Any]] = []
        for key in sorted(set(val1) | set(val2)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in val1:
                diffs.append((path, None, val2[key]))
            elif key not in val2:
                diffs.append((path, val1[key], None))
            else:
                diffs.extend(diff_json_values(val1[key], val2[key], path))
        return diffs

    if isinstance(val1, list) and isinstance(val2, list):
        diffs = []
        common_len = min(len(val1), len(val2))
        for idx in range(common_len):
            diffs.extend(diff_json_values(val1[idx], val2[idx], f"{prefix}[{idx}]"))
        for idx in range(common_len, len(val1)):
            diffs.append((f"{prefix}[{idx}]", val1[idx], None))
        for idx in range(common_len, len(val2)):
            diffs.append((f"{prefix}[{idx}]", None, val2[idx]))
        return diffs

    return [(prefix, val1, val2)]


def index_audio_tracks(
    tracks: List[Dict[str, Any]],
) -> Dict[Tuple[str, str, int], Dict[str, Any]]:
    """Indexes track entries by `(partId, instrumentId, occurrence)` for order-independent diffing."""
    counts: Dict[Tuple[str, str], int] = defaultdict(int)
    indexed: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
    for track in tracks:
        base_key = (str(track.get("partId", "")), str(track.get("instrumentId", "")))
        occ = counts[base_key]
        counts[base_key] += 1
        indexed[(base_key[0], base_key[1], occ)] = track
    return indexed


def format_track_label(key: Tuple[str, str, int]) -> str:
    part_id, inst_id, occ = key
    label = f"part {part_id or '?'} ({inst_id or 'unknown'})"
    return f"{label} #{occ + 1}" if occ > 0 else label


def summarize_track_soundfont(track: Dict[str, Any]) -> str:
    """Formats a track's input resourceMeta / soundfont configuration concisely."""
    res_meta = (track.get("in") or {}).get("resourceMeta") or {}
    attrs = res_meta.get("attributes") or {}
    parts: List[str] = []
    if res_meta.get("vendor") or res_meta.get("type"):
        parts.append("/".join(x for x in (res_meta.get("vendor"), res_meta.get("type")) if x))
    if attrs.get("soundFontName"):
        parts.append(f"soundFont={attrs['soundFontName']!r}")
    if attrs.get("presetName"):
        parts.append(f"preset={attrs['presetName']!r}")
    if attrs.get("presetBank") is not None or attrs.get("presetProgram") is not None:
        parts.append(
            f"bank={attrs.get('presetBank')}, program={attrs.get('presetProgram')}"
        )
    if not parts and res_meta.get("id"):
        parts.append(f"id={res_meta['id']!r}")
    return " | ".join(parts) or "(no soundfont metadata)"


@dataclass
class AudioDiffResult:
    """Structured diff of two MuseScore `audiosettings.json` payloads."""

    available: bool
    reason: Optional[str] = None
    global_changes: List[Dict[str, Any]] = field(default_factory=list)
    track_changes: List[Dict[str, Any]] = field(default_factory=list)
    soundfont_changes: List[Dict[str, Any]] = field(default_factory=list)
    mixer_changes: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return (
            len(self.global_changes)
            + len(self.track_changes)
            + len(self.soundfont_changes)
            + len(self.mixer_changes)
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "available": self.available,
            "global_changes": self.global_changes,
            "track_changes": self.track_changes,
            "soundfont_changes": self.soundfont_changes,
            "mixer_changes": self.mixer_changes,
            "total_changes": self.total_changes,
        }
        if self.reason is not None:
            out["reason"] = self.reason
        return out


def _try_load_audio(
    score: Path | str | MuseScoreArchive,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    if isinstance(score, MuseScoreArchive):
        return score.source_path.name, (score.audio_settings or None)
    p = Path(score)
    if not p.is_file():
        raise FileNotFoundError(f"Score file not found: {p}")
    if p.suffix.lower() not in MUSESCORE_EXTENSIONS:
        return p.name, None
    data = MuseScoreArchive.load(p).audio_settings
    return p.name, (data or None)


def diff_audio_settings_dicts(
    audio1: Optional[Dict[str, Any]],
    audio2: Optional[Dict[str, Any]],
    missing_names: Optional[List[str]] = None,
) -> AudioDiffResult:
    """Compares two already-loaded `audiosettings.json` dicts."""
    if audio1 is None or audio2 is None:
        reason = (
            f"audiosettings.json not present for: {', '.join(missing_names)}"
            if missing_names
            else "audiosettings.json not present"
        )
        return AudioDiffResult(available=False, reason=reason)

    global_changes: List[Dict[str, Any]] = []
    for key in sorted((set(audio1) | set(audio2)) - {"tracks"}):
        for path, old_val, new_val in diff_json_values(
            audio1.get(key), audio2.get(key), key
        ):
            global_changes.append({"field": path, "old": old_val, "new": new_val})

    tracks1 = index_audio_tracks(audio1.get("tracks") or [])
    tracks2 = index_audio_tracks(audio2.get("tracks") or [])

    track_changes: List[Dict[str, Any]] = []
    soundfont_changes: List[Dict[str, Any]] = []
    mixer_changes: List[Dict[str, Any]] = []

    for key in sorted(set(tracks1) | set(tracks2)):
        label = format_track_label(key)
        if key not in tracks1:
            track_changes.append({
                "op": "added",
                "track": label,
                "partId": key[0],
                "instrumentId": key[1],
                "soundfont": summarize_track_soundfont(tracks2[key]),
            })
            continue
        if key not in tracks2:
            track_changes.append({
                "op": "removed",
                "track": label,
                "partId": key[0],
                "instrumentId": key[1],
                "soundfont": summarize_track_soundfont(tracks1[key]),
            })
            continue

        t1, t2 = tracks1[key], tracks2[key]
        for path, old_val, new_val in diff_json_values(t1.get("in"), t2.get("in"), "in"):
            soundfont_changes.append({
                "track": label,
                "partId": key[0],
                "instrumentId": key[1],
                "field": path,
                "old": old_val,
                "new": new_val,
            })

        for subk in sorted((set(t1) | set(t2)) - {"in", "partId", "instrumentId"}):
            for path, old_val, new_val in diff_json_values(
                t1.get(subk), t2.get(subk), subk
            ):
                mixer_changes.append({
                    "track": label,
                    "partId": key[0],
                    "instrumentId": key[1],
                    "field": path,
                    "old": old_val,
                    "new": new_val,
                })

    return AudioDiffResult(
        available=True,
        global_changes=global_changes,
        track_changes=track_changes,
        soundfont_changes=soundfont_changes,
        mixer_changes=mixer_changes,
    )


def diff_audio_settings(
    score1: Path | str | MuseScoreArchive,
    score2: Path | str | MuseScoreArchive,
) -> AudioDiffResult:
    """Compares MuseScore `audiosettings.json` between two scores or archives."""
    name1, audio1 = _try_load_audio(score1)
    name2, audio2 = _try_load_audio(score2)
    missing = [n for n, a in ((name1, audio1), (name2, audio2)) if a is None]
    return diff_audio_settings_dicts(audio1, audio2, missing_names=missing)


def format_audio_diff(audio_diff: AudioDiffResult | Dict[str, Any]) -> str:
    """Formats an audio-settings diff into a human-readable report."""
    d = audio_diff.to_dict() if isinstance(audio_diff, AudioDiffResult) else audio_diff
    if not d.get("available"):
        return f"Audio settings diff skipped ({d.get('reason', 'unavailable')})."

    if d["total_changes"] == 0:
        return "Audio settings & soundfonts are identical (0 changes)."

    lines: List[str] = [
        f"Audio Settings / Soundfont Diff ({d['total_changes']} change(s)):"
    ]
    if d["soundfont_changes"]:
        lines.append("  Soundfont / Preset changes:")
        for ch in d["soundfont_changes"]:
            lines.append(
                f"    ~ {ch['track']} {ch['field']}: {ch['old']!r} -> {ch['new']!r}"
            )

    if d["track_changes"]:
        lines.append("  Track audio additions / removals:")
        for ch in d["track_changes"]:
            sign = "+" if ch["op"] == "added" else "-"
            lines.append(f"    {sign} {ch['track']}: {ch['soundfont']}")

    if d["global_changes"]:
        lines.append("  Global / Sound Profile / Master / Aux changes:")
        for ch in d["global_changes"]:
            lines.append(f"    ~ {ch['field']}: {ch['old']!r} -> {ch['new']!r}")

    if d["mixer_changes"]:
        lines.append("  Track mixer / FX / mute-solo changes:")
        for ch in d["mixer_changes"]:
            lines.append(
                f"    ~ {ch['track']} {ch['field']}: {ch['old']!r} -> {ch['new']!r}"
            )

    return "\n".join(lines)
