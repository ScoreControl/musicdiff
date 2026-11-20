# ------------------------------------------------------------------------------
# Purpose:       MuseScore 3-way merge and 2-way selective cherry-pick subpackage.
# ------------------------------------------------------------------------------
"""Score merging engine for MuseScore (.mscz / .mscx) files."""

from musicdiff.merge.archive_merger import (
    cherry_pick_scores,
    merge_audio_settings_3way,
    merge_scores,
    merge_style_3way,
)
from musicdiff.merge.models import MergeConflict, MergeResult
from musicdiff.merge.mscx_merger import (
    cherry_pick_measures,
    merge_mscx_3way,
    validate_staff_spanners,
)

__all__ = [
    "MergeConflict",
    "MergeResult",
    "cherry_pick_measures",
    "cherry_pick_scores",
    "merge_audio_settings_3way",
    "merge_mscx_3way",
    "merge_scores",
    "merge_style_3way",
    "validate_staff_spanners",
]
