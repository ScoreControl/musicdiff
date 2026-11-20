# ------------------------------------------------------------------------------
# Purpose:       CLI entry point (`score-extract`) for extracting MusicXML,
#                metadata, instrumentation, and audiosettings from .mscz/.mscx.
# ------------------------------------------------------------------------------
"""CLI tool for extracting MusicXML, metadata, and audio settings from MuseScore files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from musicdiff.musescore.archive import extract_audio_settings, extract_metadata
from musicdiff.musescore.exporter import export_musicxml


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="score-extract",
        description="Extract MusicXML, metadata, and audio settings from MuseScore files (.mscz / .mscx).",
    )
    parser.add_argument("score", type=Path, help="Path to .mscz or .mscx score file")
    parser.add_argument("-o", "--output-xml", type=Path, help="Destination .musicxml path")
    parser.add_argument("-m", "--metadata-out", type=Path, help="Destination .json path for metadata")
    parser.add_argument("-a", "--audio-out", type=Path, help="Destination .json path for audiosettings.json")
    parser.add_argument("--print-meta", action="store_true", help="Print extracted metadata JSON to stdout")
    parser.add_argument("--meta-only", action="store_true", help="Only extract metadata (skip MusicXML export)")
    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Only extract audiosettings.json (soundfonts, mixer, FX; skips MusicXML export)",
    )
    parser.add_argument("--xml-only", action="store_true", help="Only export MusicXML (skip saving metadata JSON)")

    args = parser.parse_args()

    if args.audio_only:
        audio_settings = extract_audio_settings(args.score)
        if args.audio_out is not None:
            _write_json(args.audio_out, audio_settings)
            print(f"Saved audio settings JSON to: {args.audio_out}")
        else:
            print(json.dumps(audio_settings, indent=2))
        return

    metadata = extract_metadata(args.score)

    if args.print_meta or args.meta_only:
        print(json.dumps(metadata, indent=2))

    if not args.xml_only and args.metadata_out is not None:
        _write_json(args.metadata_out, metadata)
        print(f"Saved metadata JSON to: {args.metadata_out}")

    if not args.xml_only and args.audio_out is not None:
        _write_json(args.audio_out, metadata.get("audioSettings", {}))
        print(f"Saved audio settings JSON to: {args.audio_out}")

    if not args.meta_only:
        out_xml = args.output_xml or args.score.with_suffix(".musicxml")
        exported = export_musicxml(args.score, out_xml)
        print(f"Exported MusicXML to: {exported}")


if __name__ == "__main__":
    main()
