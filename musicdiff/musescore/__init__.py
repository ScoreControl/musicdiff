# ------------------------------------------------------------------------------
# Purpose:       MuseScore (.mscz / .mscx) decomposition, MusicXML export, and
#                proprietary metadata / audio settings diffing.
# ------------------------------------------------------------------------------
"""MuseScore archive decomposition, export, and proprietary diffing subpackage."""

from musicdiff.musescore.archive import (
    MuseScoreArchive,
    extract_audio_settings,
    extract_metadata,
    parse_mscx_element_tree,
    track_sort_key,
)
from musicdiff.musescore.audio_diff import (
    AudioDiffResult,
    diff_audio_settings,
    diff_audio_settings_dicts,
    diff_json_values,
    format_audio_diff,
    index_audio_tracks,
)
from musicdiff.musescore.exporter import (
    MUSESCORE_EXTENSIONS,
    MUSICXML_EXTENSIONS,
    configure_music21_musescore,
    export_musicxml,
    find_musescore_binary,
    resolve_to_musicxml,
)
from musicdiff.musescore.meta_diff import (
    MetaDiffResult,
    diff_musescore_metadata,
    format_meta_diff,
)

__all__ = [
    "AudioDiffResult",
    "MUSESCORE_EXTENSIONS",
    "MUSICXML_EXTENSIONS",
    "MetaDiffResult",
    "MuseScoreArchive",
    "configure_music21_musescore",
    "diff_audio_settings",
    "diff_audio_settings_dicts",
    "diff_json_values",
    "diff_musescore_metadata",
    "export_musicxml",
    "extract_audio_settings",
    "extract_metadata",
    "find_musescore_binary",
    "format_audio_diff",
    "format_meta_diff",
    "index_audio_tracks",
    "parse_mscx_element_tree",
    "resolve_to_musicxml",
    "track_sort_key",
]
