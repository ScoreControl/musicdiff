# ------------------------------------------------------------------------------
# Purpose:       Pure-Python MuseScore (.mscz / .mscx) archive decomposition
#                and lossless repackaging.
# ------------------------------------------------------------------------------
"""Pure-Python reader/writer for MuseScore (.mscz / .mscx) archives."""

from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def track_sort_key(track: Dict[str, Any]) -> Tuple[int, int | str, str]:
    """Sort key ordering numeric partIds numerically, then lexicographically."""
    part_id = str(track.get("partId", ""))
    inst_id = str(track.get("instrumentId", ""))
    if part_id.isdigit():
        return (0, int(part_id), inst_id)
    return (1, part_id, inst_id)


@dataclass
class MuseScoreArchive:
    """In-memory representation of a decomposed MuseScore (.mscz or .mscx) file.

    Preserves all proprietary MuseScore archive members so that edits to `.mscx`,
    `audiosettings.json`, `score_style.mss`, or `automation.json` can be written
    back to a valid `.mscz` archive without MusicXML round-trip data loss.
    """

    source_path: Path
    mscx_name: str
    mscx_root: ET.Element
    audio_settings: Dict[str, Any] = field(default_factory=dict)
    score_style_root: Optional[ET.Element] = None
    automation: Optional[Dict[str, Any]] = None
    other_files: Dict[str, bytes] = field(default_factory=dict)
    has_audio_settings: bool = False

    @classmethod
    def load(cls, score_path: Path | str) -> "MuseScoreArchive":
        """Loads a `.mscz` ZIP archive or standalone `.mscx` file in pure Python."""
        path = Path(score_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        suffix = path.suffix.lower()
        if suffix == ".mscz":
            return cls._load_mscz(path)
        if suffix == ".mscx":
            return cls._load_mscx(path)
        raise ValueError(
            f"Unsupported MuseScore format '{path.suffix}'. Expected .mscz or .mscx."
        )

    @classmethod
    def _load_mscz(cls, path: Path) -> "MuseScoreArchive":
        mscx_name: Optional[str] = None
        mscx_root: Optional[ET.Element] = None
        audio_settings: Dict[str, Any] = {}
        has_audio_settings = False
        score_style_root: Optional[ET.Element] = None
        automation: Optional[Dict[str, Any]] = None
        other_files: Dict[str, bytes] = {}

        with zipfile.ZipFile(path, "r") as archive:
            for name in archive.namelist():
                raw = archive.read(name)
                if name.endswith(".mscx") and mscx_name is None:
                    mscx_name = name
                    mscx_root = ET.fromstring(raw)
                elif name == "audiosettings.json":
                    has_audio_settings = True
                    audio_settings = _normalize_audio_settings(
                        json.loads(raw.decode("utf-8"))
                    )
                elif name == "score_style.mss":
                    score_style_root = ET.fromstring(raw)
                elif name == "automation.json":
                    try:
                        automation = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError:
                        other_files[name] = raw
                else:
                    other_files[name] = raw

        if mscx_name is None or mscx_root is None:
            raise ValueError(f"No .mscx file found inside {path.name}")

        return cls(
            source_path=path,
            mscx_name=mscx_name,
            mscx_root=mscx_root,
            audio_settings=audio_settings,
            score_style_root=score_style_root,
            automation=automation,
            other_files=other_files,
            has_audio_settings=has_audio_settings,
        )

    @classmethod
    def _load_mscx(cls, path: Path) -> "MuseScoreArchive":
        mscx_root = ET.parse(path).getroot()
        audio_settings: Dict[str, Any] = {}
        has_audio_settings = False
        score_style_root: Optional[ET.Element] = None
        automation: Optional[Dict[str, Any]] = None

        audio_sibling = path.parent / "audiosettings.json"
        if audio_sibling.is_file():
            has_audio_settings = True
            audio_settings = _normalize_audio_settings(
                json.loads(audio_sibling.read_text(encoding="utf-8"))
            )

        style_sibling = path.parent / "score_style.mss"
        if style_sibling.is_file():
            score_style_root = ET.parse(style_sibling).getroot()

        auto_sibling = path.parent / "automation.json"
        if auto_sibling.is_file():
            try:
                automation = json.loads(auto_sibling.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass

        return cls(
            source_path=path,
            mscx_name=path.name,
            mscx_root=mscx_root,
            audio_settings=audio_settings,
            score_style_root=score_style_root,
            automation=automation,
            has_audio_settings=has_audio_settings,
        )

    def clone(self) -> "MuseScoreArchive":
        """Returns a deep copy of this archive suitable for mutation during merge."""
        return MuseScoreArchive(
            source_path=self.source_path,
            mscx_name=self.mscx_name,
            mscx_root=copy.deepcopy(self.mscx_root),
            audio_settings=copy.deepcopy(self.audio_settings),
            score_style_root=copy.deepcopy(self.score_style_root)
            if self.score_style_root is not None
            else None,
            automation=copy.deepcopy(self.automation)
            if self.automation is not None
            else None,
            other_files=dict(self.other_files),
            has_audio_settings=self.has_audio_settings,
        )

    def get_score_element(self) -> ET.Element:
        """Returns the `<Score>` element inside `.mscx` (or root if absent)."""
        score_el = self.mscx_root.find("Score")
        return score_el if score_el is not None else self.mscx_root

    def extract_metadata(self) -> Dict[str, Any]:
        """Extracts score metadata, full instrumentation, and audio settings."""
        score_el = self.get_score_element()

        meta: Dict[str, Any] = {}
        for meta_tag in score_el.findall("metaTag"):
            name = meta_tag.get("name")
            val = (meta_tag.text or "").strip()
            if name and val:
                meta[name] = val

        staves = score_el.findall("Staff")
        if staves:
            meta["measureCount"] = len(staves[0].findall("Measure"))
            meta["staffCount"] = len(staves)

        instruments: List[Dict[str, Any]] = []
        for part in score_el.findall("Part"):
            part_info: Dict[str, Any] = {
                "partId": part.get("id"),
                "trackName": (part.findtext("trackName") or "").strip(),
            }
            inst = part.find("Instrument")
            if inst is not None:
                part_info.update({
                    "instrumentId": (
                        inst.get("id") or inst.findtext("instrumentId") or ""
                    ).strip(),
                    "longName": (inst.findtext("longName") or "").strip(),
                    "shortName": (inst.findtext("shortName") or "").strip(),
                    "clef": (inst.findtext("clef") or "").strip(),
                })
                channel = inst.find("Channel")
                if channel is not None:
                    prog = channel.find("program")
                    part_info["midiChannel"] = channel.findtext("midiChannel")
                    part_info["midiProgram"] = (
                        prog.get("value") if prog is not None else None
                    )
                    part_info["synthesizer"] = channel.findtext("synti")

            instruments.append(part_info)

        return {
            "file": self.source_path.name,
            "metadata": meta,
            "instrumentation": instruments,
            "audioSettings": self.audio_settings,
        }

    def save(self, output_path: Path | str) -> Path:
        """Writes the archive out to a `.mscz` ZIP file or `.mscx` XML file."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        mscx_bytes = _serialize_xml(self.mscx_root)
        if out.suffix.lower() == ".mscx":
            out.write_bytes(mscx_bytes)
            return out

        # Default to .mscz zip archive
        mscx_entry_name = self.mscx_name
        container_xml = self.other_files.get("META-INF/container.xml")
        if container_xml is None:
            container_xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<container>\n"
                "  <rootfiles>\n"
                f'    <rootfile full-path="{mscx_entry_name}"/>\n'
                "  </rootfiles>\n"
                "</container>\n"
            ).encode("utf-8")

        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("META-INF/container.xml", container_xml)
            zf.writestr(mscx_entry_name, mscx_bytes)

            if self.has_audio_settings or self.audio_settings:
                zf.writestr(
                    "audiosettings.json",
                    json.dumps(self.audio_settings, indent=4).encode("utf-8"),
                )

            if self.score_style_root is not None:
                zf.writestr("score_style.mss", _serialize_xml(self.score_style_root))

            if self.automation is not None:
                zf.writestr(
                    "automation.json",
                    json.dumps(self.automation, indent=2).encode("utf-8"),
                )

            for name, raw in self.other_files.items():
                if name == "META-INF/container.xml":
                    continue
                zf.writestr(name, raw)

        return out


def _normalize_audio_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(data.get("tracks"), list):
        return {**data, "tracks": sorted(data["tracks"], key=track_sort_key)}
    return data


def _serialize_xml(root: ET.Element) -> bytes:
    body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return body if body.endswith(b"\n") else body + b"\n"


# Convenience functional API (backward-compatible with score-algorithms/extract_score.py)

def parse_mscx_element_tree(score_path: Path | str) -> ET.Element:
    """Parses root XML Element from either a .mscz zip archive or a .mscx file."""
    return MuseScoreArchive.load(score_path).mscx_root


def extract_audio_settings(score_path: Path | str) -> Dict[str, Any]:
    """Extracts MuseScore's audiosettings.json (soundfonts, mixer, FX) in pure Python."""
    return MuseScoreArchive.load(score_path).audio_settings


def extract_metadata(score_path: Path | str) -> Dict[str, Any]:
    """Extracts score properties, instrumentation, and audioSettings in pure Python."""
    return MuseScoreArchive.load(score_path).extract_metadata()
