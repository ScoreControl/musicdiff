# ------------------------------------------------------------------------------
# Purpose:       Measure-level 3-way XML merge and 2-way cherry-pick on
#                MuseScore .mscx trees with cross-measure spanner validation.
# ------------------------------------------------------------------------------
"""Pure-Python 3-way XML merger for MuseScore `.mscx` score trees."""

from __future__ import annotations

import copy
import difflib
import hashlib
import xml.etree.ElementTree as ET
from typing import Callable, Dict, List, Optional, Tuple

from musicdiff.merge.models import MergeConflict


ResolverFn = Callable[[MergeConflict], str]  # returns "ours", "theirs", or "base"


def _canonical_xml_hash(el: ET.Element) -> str:
    """Produces a deterministic whitespace-normalized hash for an XML element."""
    parts: List[str] = []

    def _walk(node: ET.Element) -> None:
        attrs = sorted(node.attrib.items())
        parts.append(f"<{node.tag}")
        for k, v in attrs:
            parts.append(f" {k}={v!r}")
        parts.append(">")
        if node.text and node.text.strip():
            parts.append(node.text.strip())
        for child in node:
            _walk(child)
        parts.append(f"</{node.tag}>")

    _walk(el)
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()


def _summarize_measure(measure: Optional[ET.Element]) -> str:
    """Returns a concise summary of a `<Measure>` element for conflict reporting."""
    if measure is None:
        return "(deleted)"
    voices = measure.findall("voice")
    chord_count = sum(len(v.findall("Chord")) for v in voices)
    rest_count = sum(len(v.findall("Rest")) for v in voices)
    spanners = [
        sp.get("type", "Spanner")
        for v in voices
        for sp in v.findall(".//Spanner")
    ]
    sp_str = f", spanners={spanners}" if spanners else ""
    return f"{len(voices)} voice(s), {chord_count} chord(s), {rest_count} rest(s){sp_str}"


def _resolve_conflict(
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
    return "ours"  # placeholder for in-memory tree; caller checks unresolved_conflicts


def _merge_sequence_3way(
    base_items: List[ET.Element],
    ours_items: List[ET.Element],
    theirs_items: List[ET.Element],
    staff_id: str,
    strategy: str,
    resolver: Optional[ResolverFn],
    conflicts: List[MergeConflict],
    stats: Dict[str, int],
) -> List[ET.Element]:
    """Performs a 3-way merge of `<Measure>` sequences for a single `<Staff>`.

    Uses SequenceMatcher on canonical XML hashes to align base->ours and base->theirs,
    handling in-place measure edits as well as insertions and deletions.
    """
    b_hashes = [_canonical_xml_hash(m) for m in base_items]
    o_hashes = [_canonical_xml_hash(m) for m in ours_items]
    t_hashes = [_canonical_xml_hash(m) for m in theirs_items]

    # Map each base index i to (op, replacement_elements) for ours and theirs.
    # Also track insertions *before* base index i (and at len(base_items) for tail).
    def _extract_edits(
        target_items: List[ET.Element], target_hashes: List[str]
    ) -> Tuple[
        Dict[int, List[ET.Element]],  # insertions before base index i
        Dict[int, Tuple[str, Optional[ET.Element]]],  # per-base-index edit ("equal"|"replace"|"delete")
    ]:
        inserts: Dict[int, List[ET.Element]] = {}
        edits: Dict[int, Tuple[str, Optional[ET.Element]]] = {}
        sm = difflib.SequenceMatcher(None, b_hashes, target_hashes, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for bi, tj in zip(range(i1, i2), range(j1, j2)):
                    edits[bi] = ("equal", target_items[tj])
            elif tag == "insert":
                inserts.setdefault(i1, []).extend(target_items[j1:j2])
            elif tag == "delete":
                for bi in range(i1, i2):
                    edits[bi] = ("delete", None)
            elif tag == "replace":
                common = min(i2 - i1, j2 - j1)
                for k in range(common):
                    edits[i1 + k] = ("replace", target_items[j1 + k])
                for bi in range(i1 + common, i2):
                    edits[bi] = ("delete", None)
                if j2 - j1 > common:
                    inserts.setdefault(i2, []).extend(target_items[j1 + common : j2])
        return inserts, edits

    o_ins, o_edits = _extract_edits(ours_items, o_hashes)
    t_ins, t_edits = _extract_edits(theirs_items, t_hashes)

    merged: List[ET.Element] = []

    def _handle_insertion(pos: int) -> None:
        oi = o_ins.get(pos, [])
        ti = t_ins.get(pos, [])
        if not oi and not ti:
            return
        if oi and not ti:
            merged.extend(copy.deepcopy(m) for m in oi)
            stats["measures_from_ours"] = stats.get("measures_from_ours", 0) + len(oi)
            return
        if ti and not oi:
            merged.extend(copy.deepcopy(m) for m in ti)
            stats["measures_from_theirs"] = stats.get("measures_from_theirs", 0) + len(ti)
            return
        # Both sides inserted at the same position
        if [_canonical_xml_hash(m) for m in oi] == [_canonical_xml_hash(m) for m in ti]:
            merged.extend(copy.deepcopy(m) for m in oi)
            stats["measures_unchanged"] = stats.get("measures_unchanged", 0) + len(oi)
            return

        conflict = MergeConflict(
            layer="notation",
            location=f"staff {staff_id}, before measure {pos + 1}",
            description=(
                f"Both sides inserted different measure(s) before measure {pos + 1} "
                f"(ours: {len(oi)}, theirs: {len(ti)})"
            ),
            ours_summary=f"{len(oi)} inserted measure(s)",
            theirs_summary=f"{len(ti)} inserted measure(s)",
            staff_id=staff_id,
            measure_number=pos + 1,
        )
        choice = _resolve_conflict(conflict, strategy, resolver)
        conflicts.append(conflict)
        if choice == "theirs":
            merged.extend(copy.deepcopy(m) for m in ti)
        elif choice == "ours":
            merged.extend(copy.deepcopy(m) for m in oi)
        # choice == "base" drops both insertions

    for bi, base_m in enumerate(base_items):
        _handle_insertion(bi)

        o_op, o_el = o_edits.get(bi, ("equal", base_m))
        t_op, t_el = t_edits.get(bi, ("equal", base_m))

        if o_op == "equal" and t_op == "equal":
            merged.append(copy.deepcopy(base_m))
            stats["measures_unchanged"] = stats.get("measures_unchanged", 0) + 1
        elif o_op != "equal" and t_op == "equal":
            if o_el is not None:
                merged.append(copy.deepcopy(o_el))
            stats["measures_from_ours"] = stats.get("measures_from_ours", 0) + 1
        elif o_op == "equal" and t_op != "equal":
            if t_el is not None:
                merged.append(copy.deepcopy(t_el))
            stats["measures_from_theirs"] = stats.get("measures_from_theirs", 0) + 1
        else:
            # Both sides modified or deleted this measure
            o_hash = _canonical_xml_hash(o_el) if o_el is not None else None
            t_hash = _canonical_xml_hash(t_el) if t_el is not None else None
            if o_hash == t_hash:
                if o_el is not None:
                    merged.append(copy.deepcopy(o_el))
                stats["measures_unchanged"] = stats.get("measures_unchanged", 0) + 1
            else:
                conflict = MergeConflict(
                    layer="notation",
                    location=f"staff {staff_id}, measure {bi + 1}",
                    description=(
                        f"Conflicting edits in staff {staff_id}, measure {bi + 1} "
                        f"(ours: {o_op}, theirs: {t_op})"
                    ),
                    base_summary=_summarize_measure(base_m),
                    ours_summary=_summarize_measure(o_el),
                    theirs_summary=_summarize_measure(t_el),
                    staff_id=staff_id,
                    measure_number=bi + 1,
                )
                choice = _resolve_conflict(conflict, strategy, resolver)
                conflicts.append(conflict)
                chosen = o_el if choice == "ours" else (t_el if choice == "theirs" else base_m)
                if chosen is not None:
                    merged.append(copy.deepcopy(chosen))

    # Tail insertions after the last base measure
    _handle_insertion(len(base_items))
    return merged


def validate_staff_spanners(
    staff_el: ET.Element, staff_id: str
) -> List[MergeConflict]:
    """Checks that cross-measure `<Spanner>` `<next>`/`<prev>` pairs remain balanced."""
    open_counts: Dict[str, int] = {}
    warnings: List[MergeConflict] = []
    for m_idx, measure in enumerate(staff_el.findall("Measure"), start=1):
        for spanner in measure.findall(".//Spanner"):
            sp_type = spanner.get("type", "Unknown")
            has_next = spanner.find("next") is not None
            has_prev = spanner.find("prev") is not None
            if has_next and not has_prev:
                open_counts[sp_type] = open_counts.get(sp_type, 0) + 1
            elif has_prev and not has_next:
                cur = open_counts.get(sp_type, 0)
                if cur <= 0:
                    warnings.append(
                        MergeConflict(
                            layer="spanner",
                            location=f"staff {staff_id}, measure {m_idx}",
                            description=(
                                f"Unmatched closing <Spanner type='{sp_type}'> "
                                f"after measure merge"
                            ),
                            staff_id=staff_id,
                            measure_number=m_idx,
                        )
                    )
                else:
                    open_counts[sp_type] = cur - 1

    for sp_type, remaining in sorted(open_counts.items()):
        if remaining > 0:
            warnings.append(
                MergeConflict(
                    layer="spanner",
                    location=f"staff {staff_id}",
                    description=(
                        f"{remaining} unclosed <Spanner type='{sp_type}'> "
                        f"spanning across merged measure boundary"
                    ),
                    staff_id=staff_id,
                )
            )
    return warnings


def _merge_metatags_3way(
    base_score: ET.Element,
    ours_score: ET.Element,
    theirs_score: ET.Element,
    merged_score: ET.Element,
    strategy: str,
    resolver: Optional[ResolverFn],
    conflicts: List[MergeConflict],
    stats: Dict[str, int],
) -> None:
    def _to_map(el: ET.Element) -> Dict[str, str]:
        return {
            mt.get("name", ""): (mt.text or "")
            for mt in el.findall("metaTag")
            if mt.get("name")
        }

    b_map = _to_map(base_score)
    o_map = _to_map(ours_score)
    t_map = _to_map(theirs_score)

    all_keys = sorted(set(b_map) | set(o_map) | set(t_map))
    final_map: Dict[str, str] = {}

    for key in all_keys:
        bv, ov, tv = b_map.get(key), o_map.get(key), t_map.get(key)
        if ov == tv:
            if ov is not None:
                final_map[key] = ov
        elif ov == bv:
            if tv is not None:
                final_map[key] = tv
                stats["metadata_from_theirs"] = stats.get("metadata_from_theirs", 0) + 1
        elif tv == bv:
            if ov is not None:
                final_map[key] = ov
                stats["metadata_from_ours"] = stats.get("metadata_from_ours", 0) + 1
        else:
            conflict = MergeConflict(
                layer="metadata",
                location=f"metaTag[{key}]",
                description=f"Conflicting edits to metaTag '{key}'",
                base_summary=repr(bv),
                ours_summary=repr(ov),
                theirs_summary=repr(tv),
            )
            choice = _resolve_conflict(conflict, strategy, resolver)
            conflicts.append(conflict)
            chosen = ov if choice == "ours" else (tv if choice == "theirs" else bv)
            if chosen is not None:
                final_map[key] = chosen

    # Update existing metaTag elements in merged_score in-place or append new ones
    existing = {mt.get("name"): mt for mt in merged_score.findall("metaTag")}
    for name, el in list(existing.items()):
        if name not in final_map:
            merged_score.remove(el)
        else:
            el.text = final_map[name]
    for name, val in final_map.items():
        if name not in existing:
            mt = ET.SubElement(merged_score, "metaTag", {"name": name})
            mt.text = val


def _merge_parts_3way(
    base_score: ET.Element,
    ours_score: ET.Element,
    theirs_score: ET.Element,
    merged_score: ET.Element,
    strategy: str,
    resolver: Optional[ResolverFn],
    conflicts: List[MergeConflict],
    stats: Dict[str, int],
) -> None:
    def _part_map(score: ET.Element) -> Dict[str, ET.Element]:
        return {
            (p.get("id") or str(i)): p
            for i, p in enumerate(score.findall("Part"), start=1)
        }

    b_parts = _part_map(base_score)
    o_parts = _part_map(ours_score)
    t_parts = _part_map(theirs_score)

    all_ids = sorted(
        set(b_parts) | set(o_parts) | set(t_parts),
        key=lambda x: (0, int(x)) if x.isdigit() else (1, x),
    )

    merged_parts: List[ET.Element] = []
    for pid in all_ids:
        bp, op, tp = b_parts.get(pid), o_parts.get(pid), t_parts.get(pid)
        bh = _canonical_xml_hash(bp) if bp is not None else None
        oh = _canonical_xml_hash(op) if op is not None else None
        th = _canonical_xml_hash(tp) if tp is not None else None

        if oh == th:
            if op is not None:
                merged_parts.append(copy.deepcopy(op))
        elif oh == bh:
            if tp is not None:
                merged_parts.append(copy.deepcopy(tp))
                stats["parts_from_theirs"] = stats.get("parts_from_theirs", 0) + 1
        elif th == bh:
            if op is not None:
                merged_parts.append(copy.deepcopy(op))
                stats["parts_from_ours"] = stats.get("parts_from_ours", 0) + 1
        else:
            conflict = MergeConflict(
                layer="part",
                location=f"Part[id={pid}]",
                description=f"Conflicting edits to Part {pid} definition/instrumentation",
                base_summary=(bp.findtext("trackName") if bp is not None else None),
                ours_summary=(op.findtext("trackName") if op is not None else None),
                theirs_summary=(tp.findtext("trackName") if tp is not None else None),
            )
            choice = _resolve_conflict(conflict, strategy, resolver)
            conflicts.append(conflict)
            chosen = op if choice == "ours" else (tp if choice == "theirs" else bp)
            if chosen is not None:
                merged_parts.append(copy.deepcopy(chosen))

    # Replace Part elements at the position of the first existing Part
    children = list(merged_score)
    first_part_idx = next(
        (i for i, ch in enumerate(children) if ch.tag == "Part"),
        len(children),
    )
    for old_p in merged_score.findall("Part"):
        merged_score.remove(old_p)
    for offset, new_p in enumerate(merged_parts):
        merged_score.insert(first_part_idx + offset, new_p)


def merge_mscx_3way(
    base_root: ET.Element,
    ours_root: ET.Element,
    theirs_root: ET.Element,
    strategy: str = "fail",
    resolver: Optional[ResolverFn] = None,
) -> Tuple[ET.Element, List[MergeConflict], Dict[str, int]]:
    """Performs a 3-way XML merge on MuseScore `.mscx` root elements.

    Returns `(merged_root, conflicts, stats)`.
    """
    merged_root = copy.deepcopy(base_root)
    base_score = base_root.find("Score") if base_root.find("Score") is not None else base_root
    ours_score = ours_root.find("Score") if ours_root.find("Score") is not None else ours_root
    theirs_score = theirs_root.find("Score") if theirs_root.find("Score") is not None else theirs_root
    merged_score = merged_root.find("Score") if merged_root.find("Score") is not None else merged_root

    conflicts: List[MergeConflict] = []
    stats: Dict[str, int] = {}

    # 1. Merge <metaTag>
    _merge_metatags_3way(
        base_score, ours_score, theirs_score, merged_score,
        strategy, resolver, conflicts, stats,
    )

    # 2. Merge <Part> / <Instrument>
    _merge_parts_3way(
        base_score, ours_score, theirs_score, merged_score,
        strategy, resolver, conflicts, stats,
    )

    # 3. Merge <Staff> / <Measure>
    def _staff_map(score: ET.Element) -> Dict[str, ET.Element]:
        return {
            (s.get("id") or str(i)): s
            for i, s in enumerate(score.findall("Staff"), start=1)
        }

    b_staves = _staff_map(base_score)
    o_staves = _staff_map(ours_score)
    t_staves = _staff_map(theirs_score)

    all_staff_ids = sorted(
        set(b_staves) | set(o_staves) | set(t_staves),
        key=lambda x: (0, int(x)) if x.isdigit() else (1, x),
    )

    # Remove old Staff elements and rebuild in order
    for old_s in merged_score.findall("Staff"):
        merged_score.remove(old_s)

    for sid in all_staff_ids:
        bs, os_, ts = b_staves.get(sid), o_staves.get(sid), t_staves.get(sid)
        if bs is None:
            # Newly added staff
            if os_ is not None and ts is None:
                merged_score.append(copy.deepcopy(os_))
                stats["staves_from_ours"] = stats.get("staves_from_ours", 0) + 1
            elif ts is not None and os_ is None:
                merged_score.append(copy.deepcopy(ts))
                stats["staves_from_theirs"] = stats.get("staves_from_theirs", 0) + 1
            elif os_ is not None and ts is not None:
                if _canonical_xml_hash(os_) == _canonical_xml_hash(ts):
                    merged_score.append(copy.deepcopy(os_))
                else:
                    conflict = MergeConflict(
                        layer="notation",
                        location=f"staff {sid}",
                        description=f"Both sides added different Staff id={sid}",
                        staff_id=sid,
                    )
                    choice = _resolve_conflict(conflict, strategy, resolver)
                    conflicts.append(conflict)
                    if choice == "theirs":
                        merged_score.append(copy.deepcopy(ts))
                    elif choice == "ours":
                        merged_score.append(copy.deepcopy(os_))
            continue

        # Staff existed in base
        if os_ is None and ts is None:
            continue
        if os_ is None and ts is not None:
            if _canonical_xml_hash(ts) == _canonical_xml_hash(bs):
                continue  # deleted in ours, unchanged in theirs
            conflict = MergeConflict(
                layer="notation",
                location=f"staff {sid}",
                description=f"Staff {sid} deleted in ours but modified in theirs",
                staff_id=sid,
            )
            choice = _resolve_conflict(conflict, strategy, resolver)
            conflicts.append(conflict)
            if choice == "theirs":
                merged_score.append(copy.deepcopy(ts))
            elif choice == "base":
                merged_score.append(copy.deepcopy(bs))
            continue
        if ts is None and os_ is not None:
            if _canonical_xml_hash(os_) == _canonical_xml_hash(bs):
                continue  # deleted in theirs, unchanged in ours
            conflict = MergeConflict(
                layer="notation",
                location=f"staff {sid}",
                description=f"Staff {sid} deleted in theirs but modified in ours",
                staff_id=sid,
            )
            choice = _resolve_conflict(conflict, strategy, resolver)
            conflicts.append(conflict)
            if choice == "ours":
                merged_score.append(copy.deepcopy(os_))
            elif choice == "base":
                merged_score.append(copy.deepcopy(bs))
            continue

        assert os_ is not None and ts is not None
        new_staff = copy.deepcopy(bs)
        for old_m in new_staff.findall("Measure"):
            new_staff.remove(old_m)

        merged_measures = _merge_sequence_3way(
            bs.findall("Measure"),
            os_.findall("Measure"),
            ts.findall("Measure"),
            staff_id=sid,
            strategy=strategy,
            resolver=resolver,
            conflicts=conflicts,
            stats=stats,
        )
        for m in merged_measures:
            new_staff.append(m)

        # Validate cross-measure spanners
        spanner_issues = validate_staff_spanners(new_staff, sid)
        conflicts.extend(spanner_issues)

        merged_score.append(new_staff)

    return merged_root, conflicts, stats


def cherry_pick_measures(
    source_root: ET.Element,
    target_root: ET.Element,
    measure_range: Tuple[int, int],
    staff_id: Optional[str] = None,
) -> Tuple[ET.Element, Dict[str, int]]:
    """Copies 1-based inclusive `measure_range` from `source_root` into `target_root`."""
    start_m, end_m = measure_range
    if start_m < 1 or end_m < start_m:
        raise ValueError(f"Invalid measure range: {measure_range}")

    result_root = copy.deepcopy(target_root)
    src_score = source_root.find("Score") if source_root.find("Score") is not None else source_root
    dst_score = result_root.find("Score") if result_root.find("Score") is not None else result_root

    src_staves = {
        (s.get("id") or str(i)): s
        for i, s in enumerate(src_score.findall("Staff"), start=1)
    }
    dst_staves = {
        (s.get("id") or str(i)): s
        for i, s in enumerate(dst_score.findall("Staff"), start=1)
    }

    target_sids = [staff_id] if staff_id is not None else sorted(
        set(src_staves) & set(dst_staves),
        key=lambda x: (0, int(x)) if x.isdigit() else (1, x),
    )

    replaced = 0
    for sid in target_sids:
        if sid not in src_staves or sid not in dst_staves:
            raise ValueError(f"Staff '{sid}' not found in both source and target scores.")
        src_measures = src_staves[sid].findall("Measure")
        dst_staff = dst_staves[sid]
        dst_measures = dst_staff.findall("Measure")

        # Keep non-Measure children (like VBox) in place and splice Measures
        non_measure_children = [ch for ch in list(dst_staff) if ch.tag != "Measure"]
        new_measures = list(dst_measures)

        for m_num in range(start_m, end_m + 1):
            idx = m_num - 1
            if idx >= len(src_measures):
                raise IndexError(
                    f"Measure {m_num} out of range for source staff {sid} ({len(src_measures)} measures)."
                )
            src_copy = copy.deepcopy(src_measures[idx])
            if idx < len(new_measures):
                new_measures[idx] = src_copy
            else:
                new_measures.append(src_copy)
            replaced += 1

        dst_staff[:] = non_measure_children + new_measures

    return result_root, {"measures_cherry_picked": replaced}
