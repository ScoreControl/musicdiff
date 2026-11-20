# ------------------------------------------------------------------------------
# Purpose:       Data models for 3-way and selective 2-way MuseScore merging.
# ------------------------------------------------------------------------------
"""Data models for score merge operations and conflict reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class MergeConflict:
    """Represents a single merge conflict across notation, audio, metadata, or style."""

    layer: str  # "notation", "audio", "metadata", "part", "style", "automation", "spanner"
    location: str
    description: str
    base_summary: Optional[str] = None
    ours_summary: Optional[str] = None
    theirs_summary: Optional[str] = None
    staff_id: Optional[str] = None
    measure_number: Optional[int] = None
    resolution: str = "unresolved"  # "unresolved", "ours", "theirs", "base"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer": self.layer,
            "location": self.location,
            "description": self.description,
            "base_summary": self.base_summary,
            "ours_summary": self.ours_summary,
            "theirs_summary": self.theirs_summary,
            "staff_id": self.staff_id,
            "measure_number": self.measure_number,
            "resolution": self.resolution,
        }


@dataclass
class MergeResult:
    """Outcome of a 3-way merge or 2-way cherry-pick operation."""

    success: bool
    output_path: Optional[Path] = None
    conflicts: List[MergeConflict] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)

    @property
    def unresolved_conflicts(self) -> List[MergeConflict]:
        return [c for c in self.conflicts if c.resolution == "unresolved"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output_path": str(self.output_path) if self.output_path else None,
            "stats": self.stats,
            "total_conflicts": len(self.conflicts),
            "unresolved_conflicts": len(self.unresolved_conflicts),
            "conflicts": [c.to_dict() for c in self.conflicts],
        }

    def format_report(self) -> str:
        lines: List[str] = []
        status = "SUCCESS" if self.success else "CONFLICTS DETECTED"
        lines.append(f"Score Merge Result: {status}")
        if self.output_path:
            lines.append(f"  Output: {self.output_path}")
        if self.stats:
            stat_str = ", ".join(f"{k}={v}" for k, v in sorted(self.stats.items()))
            lines.append(f"  Stats:  {stat_str}")

        if not self.conflicts:
            lines.append("  Conflicts: 0")
            return "\n".join(lines)

        lines.append(
            f"  Conflicts: {len(self.conflicts)} total "
            f"({len(self.unresolved_conflicts)} unresolved)"
        )
        for idx, c in enumerate(self.conflicts, start=1):
            lines.append(
                f"    [{idx}] ({c.layer}) {c.location} [{c.resolution}]: {c.description}"
            )
            if c.ours_summary is not None:
                lines.append(f"        ours:   {c.ours_summary}")
            if c.theirs_summary is not None:
                lines.append(f"        theirs: {c.theirs_summary}")
        return "\n".join(lines)
