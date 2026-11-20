# ------------------------------------------------------------------------------
# Purpose:       MuseScore proprietary metadata, part/instrument, style
#                (score_style.mss), and automation.json diffing.
# ------------------------------------------------------------------------------
"""Diffing utilities for MuseScore proprietary `.mscx` metadata, styles, and automation."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from musicdiff.musescore.archive import MuseScoreArchive
from musicdiff.musescore.audio_diff import diff_json_values
from musicdiff.musescore.exporter import MUSESCORE_EXTENSIONS


def _extract_style_map(style_root: Optional[ET.Element]) -> Dict[str, str]:
    """Extracts `<Style>` child tags from `score_style.mss` into a flat `{tag: value}` dict."""
    if style_root is None:
        return {}
    style_el = style_root.find("Style")
    container = style_el if style_el is not None else style_root
    result: Dict[str, str] = {}
    for child in container:
        key = child.tag
        if child.attrib:
            attrs = ",".join(f"{k}={v}" for k, v in sorted(child.attrib.items()))
            key = f"{child.tag}[{attrs}]"
        if len(child) == 0:
            result[key] = (child.text or "").strip()
        else:
            result[key] = ET.tostring(child, encoding="unicode").strip()
    return result


@dataclass
class MetaDiffResult:
    """Structured diff of MuseScore proprietary metadata, instrumentation, style, and automation."""

    available: bool
    reason: Optional[str] = None
    metadata_changes: List[Dict[str, Any]] = field(default_factory=list)
    part_changes: List[Dict[str, Any]] = field(default_factory=list)
    style_changes: List[Dict[str, Any]] = field(default_factory=list)
    automation_changes: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return (
            len(self.metadata_changes)
            + len(self.part_changes)
            + len(self.style_changes)
            + len(self.automation_changes)
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "available": self.available,
            "metadata_changes": self.metadata_changes,
            "part_changes": self.part_changes,
            "style_changes": self.style_changes,
            "automation_changes": self.automation_changes,
            "total_changes": self.total_changes,
        }
        if self.reason is not None:
            out["reason"] = self.reason
        return out


def _try_load_archive(
    score: Path | str | MuseScoreArchive,
) -> tuple[str, Optional[MuseScoreArchive]]:
    if isinstance(score, MuseScoreArchive):
        return score.source_path.name, score
    p = Path(score)
    if not p.is_file():
        raise FileNotFoundError(f"Score file not found: {p}")
    if p.suffix.lower() not in MUSESCORE_EXTENSIONS:
        return p.name, None
    return p.name, MuseScoreArchive.load(p)


def diff_musescore_metadata(
    score1: Path | str | MuseScoreArchive,
    score2: Path | str | MuseScoreArchive,
) -> MetaDiffResult:
    """Compares `.mscx` metaTags, Part/Instrument definitions, `score_style.mss`, and `automation.json`."""
    name1, arch1 = _try_load_archive(score1)
    name2, arch2 = _try_load_archive(score2)
    if arch1 is None or arch2 is None:
        missing = [n for n, a in ((name1, arch1), (name2, arch2)) if a is None]
        return MetaDiffResult(
            available=False,
            reason=f"MuseScore archive not available for: {', '.join(missing)}",
        )

    meta1 = arch1.extract_metadata()
    meta2 = arch2.extract_metadata()

    # 1. metaTag & score-level properties
    metadata_changes: List[Dict[str, Any]] = []
    for path, old_val, new_val in diff_json_values(
        meta1["metadata"], meta2["metadata"]
    ):
        metadata_changes.append({"field": path, "old": old_val, "new": new_val})

    # 2. Part / Instrument definitions keyed by partId (fallback to index)
    parts1 = {
        str(p.get("partId") or idx): p
        for idx, p in enumerate(meta1["instrumentation"], start=1)
    }
    parts2 = {
        str(p.get("partId") or idx): p
        for idx, p in enumerate(meta2["instrumentation"], start=1)
    }
    part_changes: List[Dict[str, Any]] = []
    for pid in sorted(
        set(parts1) | set(parts2),
        key=lambda x: (0, int(x)) if x.isdigit() else (1, x),
    ):
        if pid not in parts1:
            part_changes.append({"op": "added", "partId": pid, "part": parts2[pid]})
        elif pid not in parts2:
            part_changes.append({"op": "removed", "partId": pid, "part": parts1[pid]})
        else:
            for field_name, old_val, new_val in diff_json_values(
                parts1[pid], parts2[pid]
            ):
                part_changes.append({
                    "op": "modified",
                    "partId": pid,
                    "field": field_name,
                    "old": old_val,
                    "new": new_val,
                })

    # 3. score_style.mss diffs
    style1 = _extract_style_map(arch1.score_style_root)
    style2 = _extract_style_map(arch2.score_style_root)
    style_changes: List[Dict[str, Any]] = []
    for key, old_val, new_val in diff_json_values(style1, style2):
        style_changes.append({"tag": key, "old": old_val, "new": new_val})

    # 4. automation.json diffs
    automation_changes: List[Dict[str, Any]] = []
    if arch1.automation is not None or arch2.automation is not None:
        for path, old_val, new_val in diff_json_values(
            arch1.automation or {}, arch2.automation or {}
        ):
            automation_changes.append({"field": path, "old": old_val, "new": new_val})

    return MetaDiffResult(
        available=True,
        metadata_changes=metadata_changes,
        part_changes=part_changes,
        style_changes=style_changes,
        automation_changes=automation_changes,
    )


def format_meta_diff(meta_diff: MetaDiffResult | Dict[str, Any]) -> str:
    """Formats a MuseScore proprietary metadata/style diff into a readable report."""
    d = meta_diff.to_dict() if isinstance(meta_diff, MetaDiffResult) else meta_diff
    if not d.get("available"):
        return f"MuseScore metadata diff skipped ({d.get('reason', 'unavailable')})."

    if d["total_changes"] == 0:
        return "MuseScore metadata, parts, style & automation are identical (0 changes)."

    lines: List[str] = [
        f"MuseScore Proprietary Diff ({d['total_changes']} change(s)):"
    ]
    if d["metadata_changes"]:
        lines.append("  Score metadata (metaTag / counts):")
        for ch in d["metadata_changes"]:
            lines.append(f"    ~ {ch['field']}: {ch['old']!r} -> {ch['new']!r}")

    if d["part_changes"]:
        lines.append("  Part / Instrument definitions (.mscx):")
        for ch in d["part_changes"]:
            if ch["op"] == "added":
                p = ch["part"]
                lines.append(
                    f"    + part {ch['partId']} ({p.get('instrumentId') or p.get('trackName')})"
                )
            elif ch["op"] == "removed":
                p = ch["part"]
                lines.append(
                    f"    - part {ch['partId']} ({p.get('instrumentId') or p.get('trackName')})"
                )
            else:
                lines.append(
                    f"    ~ part {ch['partId']} {ch['field']}: {ch['old']!r} -> {ch['new']!r}"
                )

    if d["style_changes"]:
        lines.append("  Engraving / Style (score_style.mss):")
        for ch in d["style_changes"]:
            lines.append(f"    ~ {ch['tag']}: {ch['old']!r} -> {ch['new']!r}")

    if d["automation_changes"]:
        lines.append("  Automation (automation.json):")
        for ch in d["automation_changes"]:
            lines.append(f"    ~ {ch['field']}: {ch['old']!r} -> {ch['new']!r}")

    return "\n".join(lines)
