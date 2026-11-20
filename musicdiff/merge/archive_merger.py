# ------------------------------------------------------------------------------
# Purpose:       Full 3-way .mscz archive merge & 2-way selective cherry-pick
#                combining .mscx, audiosettings.json, score_style.mss, and
#                automation.json.
# ------------------------------------------------------------------------------
"""High-level MuseScore archive merger (3-way merge and 2-way selective cherry-pick)."""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from musicdiff.merge.models import MergeConflict, MergeResult
from musicdiff.merge.mscx_merger import (
    ResolverFn,
    cherry_pick_measures,
    merge_mscx_3way,
)
from musicdiff.musescore.archive import MuseScoreArchive, track_sort_key
from musicdiff.musescore.audio_diff import format_track_label, index_audio_tracks


def _resolve(
    conflict: MergeConflict,
    strategy: str,
    resolver: Optional[ResolverFn],
) -> str:
    if resolver is not None:
        choice = resolver(conflict)
        if choice in ("ours", "theirs", "base"):
            conflict.resolution = choice
            return choice
    if strategy in ("ours", "theirs", "base"):
        conflict.resolution = strategy
        return strategy
    conflict.resolution = "unresolved"
    return "ours"


def _merge_json_3way(
    base: Any,
    ours: Any,
    theirs: Any,
    *,
    layer: str,
    prefix: str,
    strategy: str,
    resolver: Optional[ResolverFn],
    conflicts: List[MergeConflict],
    stats: Dict[str, int],
) -> Any:
    """Recursive 3-way merge for JSON dicts / scalars."""
    if ours == theirs:
        return copy.deepcopy(ours)
    if ours == base:
        stats[f"{layer}_from_theirs"] = stats.get(f"{layer}_from_theirs", 0) + 1
        return copy.deepcopy(theirs)
    if theirs == base:
        stats[f"{layer}_from_ours"] = stats.get(f"{layer}_from_ours", 0) + 1
        return copy.deepcopy(ours)

    if isinstance(base, dict) and isinstance(ours, dict) and isinstance(theirs, dict):
        merged: Dict[str, Any] = {}
        all_keys = sorted(set(base) | set(ours) | set(theirs))
        for k in all_keys:
            path = f"{prefix}.{k}" if prefix else str(k)
            in_b, in_o, in_t = k in base, k in ours, k in theirs
            bv = base.get(k)
            ov = ours.get(k)
            tv = theirs.get(k)
            if in_o == in_t and ov == tv:
                if in_o:
                    merged[k] = copy.deepcopy(ov)
            elif in_o == in_b and ov == bv:
                if in_t:
                    merged[k] = copy.deepcopy(tv)
                    stats[f"{layer}_from_theirs"] = stats.get(f"{layer}_from_theirs", 0) + 1
            elif in_t == in_b and tv == bv:
                if in_o:
                    merged[k] = copy.deepcopy(ov)
                    stats[f"{layer}_from_ours"] = stats.get(f"{layer}_from_ours", 0) + 1
            elif in_b and in_o and in_t and all(isinstance(v, dict) for v in (bv, ov, tv)):
                merged[k] = _merge_json_3way(
                    bv, ov, tv,
                    layer=layer, prefix=path, strategy=strategy,
                    resolver=resolver, conflicts=conflicts, stats=stats,
                )
            else:
                conflict = MergeConflict(
                    layer=layer,
                    location=path,
                    description=f"Conflicting {layer} change at '{path}'",
                    base_summary=repr(bv) if in_b else "(absent)",
                    ours_summary=repr(ov) if in_o else "(absent)",
                    theirs_summary=repr(tv) if in_t else "(absent)",
                )
                choice = _resolve(conflict, strategy, resolver)
                conflicts.append(conflict)
                if choice == "theirs" and in_t:
                    merged[k] = copy.deepcopy(tv)
                elif choice == "base" and in_b:
                    merged[k] = copy.deepcopy(bv)
                elif choice == "ours" and in_o:
                    merged[k] = copy.deepcopy(ov)
        return merged

    conflict = MergeConflict(
        layer=layer,
        location=prefix or layer,
        description=f"Conflicting {layer} value at '{prefix or layer}'",
        base_summary=repr(base),
        ours_summary=repr(ours),
        theirs_summary=repr(theirs),
    )
    choice = _resolve(conflict, strategy, resolver)
    conflicts.append(conflict)
    if choice == "theirs":
        return copy.deepcopy(theirs)
    if choice == "base":
        return copy.deepcopy(base)
    return copy.deepcopy(ours)


def merge_audio_settings_3way(
    base: Dict[str, Any],
    ours: Dict[str, Any],
    theirs: Dict[str, Any],
    *,
    strategy: str = "fail",
    resolver: Optional[ResolverFn] = None,
    conflicts: Optional[List[MergeConflict]] = None,
    stats: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """3-way merge of MuseScore `audiosettings.json`, keying tracks by `(partId, instrumentId, occ)`."""
    conflicts = conflicts if conflicts is not None else []
    stats = stats if stats is not None else {}

    base_global = {k: v for k, v in base.items() if k != "tracks"}
    ours_global = {k: v for k, v in ours.items() if k != "tracks"}
    theirs_global = {k: v for k, v in theirs.items() if k != "tracks"}

    merged: Dict[str, Any] = _merge_json_3way(
        base_global, ours_global, theirs_global,
        layer="audio", prefix="audiosettings",
        strategy=strategy, resolver=resolver,
        conflicts=conflicts, stats=stats,
    )

    b_tracks = index_audio_tracks(base.get("tracks") or [])
    o_tracks = index_audio_tracks(ours.get("tracks") or [])
    t_tracks = index_audio_tracks(theirs.get("tracks") or [])

    merged_tracks: List[Dict[str, Any]] = []
    for key in sorted(set(b_tracks) | set(o_tracks) | set(t_tracks)):
        bt, ot, tt = b_tracks.get(key), o_tracks.get(key), t_tracks.get(key)
        label = format_track_label(key)
        if ot == tt:
            if ot is not None:
                merged_tracks.append(copy.deepcopy(ot))
        elif ot == bt:
            if tt is not None:
                merged_tracks.append(copy.deepcopy(tt))
                stats["audio_tracks_from_theirs"] = stats.get("audio_tracks_from_theirs", 0) + 1
        elif tt == bt:
            if ot is not None:
                merged_tracks.append(copy.deepcopy(ot))
                stats["audio_tracks_from_ours"] = stats.get("audio_tracks_from_ours", 0) + 1
        elif bt is not None and ot is not None and tt is not None:
            merged_track = _merge_json_3way(
                bt, ot, tt,
                layer="audio", prefix=f"audiosettings.tracks[{label}]",
                strategy=strategy, resolver=resolver,
                conflicts=conflicts, stats=stats,
            )
            merged_tracks.append(merged_track)
        else:
            conflict = MergeConflict(
                layer="audio",
                location=f"audiosettings.tracks[{label}]",
                description=f"Conflicting addition/removal of audio track {label}",
                base_summary="present" if bt is not None else "absent",
                ours_summary="present" if ot is not None else "absent",
                theirs_summary="present" if tt is not None else "absent",
            )
            choice = _resolve(conflict, strategy, resolver)
            conflicts.append(conflict)
            chosen = ot if choice == "ours" else (tt if choice == "theirs" else bt)
            if chosen is not None:
                merged_tracks.append(copy.deepcopy(chosen))

    if merged_tracks or "tracks" in base or "tracks" in ours or "tracks" in theirs:
        merged["tracks"] = sorted(merged_tracks, key=track_sort_key)

    return merged


def merge_style_3way(
    base_root: Optional[ET.Element],
    ours_root: Optional[ET.Element],
    theirs_root: Optional[ET.Element],
    *,
    strategy: str = "fail",
    resolver: Optional[ResolverFn] = None,
    conflicts: Optional[List[MergeConflict]] = None,
    stats: Optional[Dict[str, int]] = None,
) -> Optional[ET.Element]:
    """3-way merge of `score_style.mss` XML trees keyed by style child tag."""
    conflicts = conflicts if conflicts is not None else []
    stats = stats if stats is not None else {}

    if base_root is None and ours_root is None and theirs_root is None:
        return None
    template = base_root if base_root is not None else (ours_root if ours_root is not None else theirs_root)
    assert template is not None
    merged_root = copy.deepcopy(template)

    def _style_container(root: Optional[ET.Element]) -> Optional[ET.Element]:
        if root is None:
            return None
        s = root.find("Style")
        return s if s is not None else root

    def _tag_map(container: Optional[ET.Element]) -> Dict[str, Tuple[ET.Element, str]]:
        if container is None:
            return {}
        out: Dict[str, Tuple[ET.Element, str]] = {}
        for ch in container:
            key = ch.tag
            if ch.attrib:
                attrs = ",".join(f"{k}={v}" for k, v in sorted(ch.attrib.items()))
                key = f"{ch.tag}[{attrs}]"
            out[key] = (ch, ET.tostring(ch, encoding="unicode").strip())
        return out

    b_map = _tag_map(_style_container(base_root))
    o_map = _tag_map(_style_container(ours_root))
    t_map = _tag_map(_style_container(theirs_root))

    merged_container = _style_container(merged_root)
    assert merged_container is not None
    merged_container[:] = []

    for key in sorted(set(b_map) | set(o_map) | set(t_map)):
        be, bs = b_map.get(key, (None, None))
        oe, os_ = o_map.get(key, (None, None))
        te, ts = t_map.get(key, (None, None))

        if os_ == ts:
            if oe is not None:
                merged_container.append(copy.deepcopy(oe))
        elif os_ == bs:
            if te is not None:
                merged_container.append(copy.deepcopy(te))
                stats["style_from_theirs"] = stats.get("style_from_theirs", 0) + 1
        elif ts == bs:
            if oe is not None:
                merged_container.append(copy.deepcopy(oe))
                stats["style_from_ours"] = stats.get("style_from_ours", 0) + 1
        else:
            conflict = MergeConflict(
                layer="style",
                location=f"score_style.mss/{key}",
                description=f"Conflicting engraving style change for '{key}'",
                base_summary=bs,
                ours_summary=os_,
                theirs_summary=ts,
            )
            choice = _resolve(conflict, strategy, resolver)
            conflicts.append(conflict)
            chosen = oe if choice == "ours" else (te if choice == "theirs" else be)
            if chosen is not None:
                merged_container.append(copy.deepcopy(chosen))

    return merged_root


def merge_scores(
    base: Path | str,
    ours: Path | str,
    theirs: Path | str,
    output_path: Path | str,
    *,
    strategy: str = "fail",
    resolver: Optional[ResolverFn] = None,
    write_on_conflict: bool = False,
) -> MergeResult:
    """Performs a full 3-way merge of three MuseScore (`.mscz`/`.mscx`) files.

    Merges:
      1. `.mscx` musical measures (per staff), `<metaTag>`, and `<Part>` definitions,
         with cross-measure `<Spanner>` integrity validation.
      2. `audiosettings.json` (global + track-keyed soundfonts, presets, mixer, FX).
      3. `score_style.mss` (engraving stylesheet).
      4. `automation.json` (playback automation).
    """
    if strategy not in ("fail", "ours", "theirs", "base"):
        raise ValueError(f"Unsupported merge strategy '{strategy}'. Expected fail, ours, theirs, or base.")

    base_arch = MuseScoreArchive.load(base)
    ours_arch = MuseScoreArchive.load(ours)
    theirs_arch = MuseScoreArchive.load(theirs)

    conflicts: List[MergeConflict] = []
    stats: Dict[str, int] = {}

    # 1. Merge .mscx
    merged_mscx, mscx_conflicts, mscx_stats = merge_mscx_3way(
        base_arch.mscx_root,
        ours_arch.mscx_root,
        theirs_arch.mscx_root,
        strategy=strategy,
        resolver=resolver,
    )
    conflicts.extend(mscx_conflicts)
    stats.update(mscx_stats)

    # 2. Merge audiosettings.json
    merged_audio: Dict[str, Any] = {}
    has_audio = base_arch.has_audio_settings or ours_arch.has_audio_settings or theirs_arch.has_audio_settings
    if has_audio:
        merged_audio = merge_audio_settings_3way(
            base_arch.audio_settings,
            ours_arch.audio_settings,
            theirs_arch.audio_settings,
            strategy=strategy,
            resolver=resolver,
            conflicts=conflicts,
            stats=stats,
        )

    # 3. Merge score_style.mss
    merged_style = merge_style_3way(
        base_arch.score_style_root,
        ours_arch.score_style_root,
        theirs_arch.score_style_root,
        strategy=strategy,
        resolver=resolver,
        conflicts=conflicts,
        stats=stats,
    )

    # 4. Merge automation.json
    merged_automation = None
    if any(a.automation is not None for a in (base_arch, ours_arch, theirs_arch)):
        merged_automation = _merge_json_3way(
            base_arch.automation or {},
            ours_arch.automation or {},
            theirs_arch.automation or {},
            layer="automation",
            prefix="automation",
            strategy=strategy,
            resolver=resolver,
            conflicts=conflicts,
            stats=stats,
        )

    unresolved = [c for c in conflicts if c.resolution == "unresolved"]
    out_p = Path(output_path)

    if unresolved and not write_on_conflict:
        return MergeResult(
            success=False,
            output_path=None,
            conflicts=conflicts,
            stats=stats,
        )

    merged_arch = MuseScoreArchive(
        source_path=out_p,
        mscx_name=base_arch.mscx_name,
        mscx_root=merged_mscx,
        audio_settings=merged_audio,
        score_style_root=merged_style,
        automation=merged_automation,
        other_files=dict(base_arch.other_files),
        has_audio_settings=has_audio,
    )
    saved = merged_arch.save(out_p)
    return MergeResult(
        success=len(unresolved) == 0,
        output_path=saved,
        conflicts=conflicts,
        stats=stats,
    )


def cherry_pick_scores(
    source: Path | str,
    target: Path | str,
    output_path: Path | str,
    *,
    layers: Iterable[str] = (),
    measure_range: Optional[Tuple[int, int]] = None,
    staff_id: Optional[str] = None,
) -> MergeResult:
    """Selectively copies specific layers or measure ranges from `source` onto `target`.

    Supported layers: `"audio"`, `"style"`, `"metadata"`, `"automation"`, `"notation"`.
    If `measure_range=(start, end)` (1-based inclusive) is provided, copies those
    measures from `source` into `target` (optionally scoped to `staff_id`).
    """
    src_arch = MuseScoreArchive.load(source)
    dst_arch = MuseScoreArchive.load(target).clone()
    layer_set = {layer.strip().lower() for layer in layers}
    stats: Dict[str, int] = {}

    if "audio" in layer_set:
        dst_arch.audio_settings = copy.deepcopy(src_arch.audio_settings)
        dst_arch.has_audio_settings = src_arch.has_audio_settings
        stats["audio_copied"] = 1

    if "style" in layer_set and src_arch.score_style_root is not None:
        dst_arch.score_style_root = copy.deepcopy(src_arch.score_style_root)
        stats["style_copied"] = 1

    if "automation" in layer_set and src_arch.automation is not None:
        dst_arch.automation = copy.deepcopy(src_arch.automation)
        stats["automation_copied"] = 1

    if "metadata" in layer_set:
        src_score = src_arch.get_score_element()
        dst_score = dst_arch.get_score_element()
        for old_mt in dst_score.findall("metaTag"):
            dst_score.remove(old_mt)
        for src_mt in src_score.findall("metaTag"):
            dst_score.append(copy.deepcopy(src_mt))
        stats["metadata_copied"] = len(src_score.findall("metaTag"))

    if measure_range is not None:
        dst_arch.mscx_root, m_stats = cherry_pick_measures(
            src_arch.mscx_root,
            dst_arch.mscx_root,
            measure_range=measure_range,
            staff_id=staff_id,
        )
        stats.update(m_stats)

    saved = dst_arch.save(output_path)
    return MergeResult(success=True, output_path=saved, conflicts=[], stats=stats)
