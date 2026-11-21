# Testing Guide (`TEST.md`)

Complete reference for testing every modality of this consolidated `musicdiff` library (notation, glissandos, instrumentation, MuseScore `.mscz`/`.mscx` decomposition, proprietary audio/style/metadata diffing, annotated PDF rendering, and 3-way/2-way score merging) from both **shell** and **Python**.

---

## 0. Environment Setup

Activate the `score-algos` Conda environment (which has `music21`, `converter21`, `numpy`, and MuseScore) and install this repo in editable mode so `score-diff`, `score-extract`, `score-merge`, and `import musicdiff` all resolve to `/home/shojha/musicdiff`:

```bash
conda activate score-algos
cd /home/shojha/musicdiff
pip install -e .
```

> **Note:** If MuseScore is installed in a non-standard location, set `MUSESCORE_BIN=/path/to/mscore`.

---

## 1. Automated Test Suites

### A. Consolidated Glissando, Instrument, Proprietary Diff & Merge Suite
```bash
python -m unittest discover -s tests -p "test_consolidated.py" -v
```
Covers:
- Glissando insertion and `linetype` (`solid` vs `wavy`) changes (`tests/gliss_scores/Test2_*.mxl`)
- Part-level and mid-score instrument changes + `DetailLevel.Instruments` toggling
- `audiosettings.json` soundfont, preset, and mixer diffs
- `.mscx` `metaTag`, `<Part>`, and `score_style.mss` diffs
- 3-way `.mscz` clean merge, conflict detection (`fail`/`ours`/`theirs`/`base`), cross-measure `<Spanner>` validation, and 2-way selective cherry-pick

### B. Upstream `musicdiff` Regression Suites
```bash
# Individual unit test modules (note: run from repo root)
python tests/test_nl.py
python tests/test_scl.py
python tests/test_utils.py
python tests/test_score_visualization.py

# CLI regression suite (requires zsh)
zsh tests/test_cmd_line

# Coverage diff regression (requires zsh)
zsh tests/test_coverage
```

---

## 2. Shell / CLI Modalities

All diff commands below work via either `python -m musicdiff ...` or the `score-diff ...` console script (after `pip install -e .`), and accept `.mscz`, `.mscx`, `.musicxml`, `.xml`, `.mxl`, `.mei`, and other `music21`-supported formats.

### 2.1 Notation Diff (Text Output)
```bash
# Glissando diff on MusicXML (.mxl)
python -m musicdiff tests/gliss_scores/Test2_Base.mxl tests/gliss_scores/Test2_Gliss.mxl -o text
python -m musicdiff tests/gliss_scores/Test2_Gliss.mxl tests/gliss_scores/Test2_Gliss_Change.mxl -o text

# Full MuseScore (.mscz) diff: notation + glissandos + instruments + audio + metadata/style
python -m musicdiff \
  /home/shojha/score-algorithms/msczs/tbd-ss-8-12.mscz \
  /home/shojha/score-algorithms/msczs/tbd-ss-8-16.mscz \
  -o text
```

### 2.2 Machine-Readable JSON Diff
```bash
python -m musicdiff \
  /home/shojha/score-algorithms/msczs/tbd-ss-8-12.mscz \
  /home/shojha/score-algorithms/msczs/tbd-ss-8-16.mscz \
  -o json > /tmp/diff_report.json
```

### 2.3 Annotated Visual Diff PDFs
```bash
# Save marked-up PDFs to explicit output paths (plus text summary)
python -m musicdiff \
  tests/gliss_scores/Test2_Base.mxl \
  tests/gliss_scores/Test2_Gliss.mxl \
  -o visual text \
  --pdf-out /tmp/base_diff.pdf /tmp/gliss_diff.pdf

# Real .mscz files -> auto-exports MusicXML and renders annotated PDFs
python -m musicdiff \
  /home/shojha/score-algorithms/msczs/tbd-ss-8-12.mscz \
  /home/shojha/score-algorithms/msczs/tbd-ss-half-step-down.mscz \
  -o visual text \
  --pdf-out /tmp/s1_diff.pdf /tmp/s2_diff.pdf

# Open annotated PDFs directly in the system default PDF viewer
python -m musicdiff tests/gliss_scores/Test2_Base.mxl tests/gliss_scores/Test2_Gliss.mxl -o visual
```

### 2.4 Fast Pure-Python MuseScore Proprietary Diffs (No MuseScore CLI Required)
```bash
# Audio settings only (soundfonts, presets, mixer volume/pan/mute/solo, FX)
python -m musicdiff \
  /home/shojha/score-algorithms/msczs/tbd-ss-8-12.mscz \
  /home/shojha/score-algorithms/msczs/tbd-ss-8-16.mscz \
  --audio-only

# All proprietary layers (audiosettings.json + .mscx metaTags/Parts + score_style.mss + automation.json)
python -m musicdiff \
  /home/shojha/score-algorithms/msczs/tbd-ss-8-12.mscz \
  /home/shojha/score-algorithms/msczs/tbd-ss-8-16.mscz \
  --proprietary-only
```

### 2.5 Detail-Level Filtering (`-i` / `--include`, `-x` / `--exclude`)
```bash
# Only glissandos + notes
python -m musicdiff tests/gliss_scores/Test2_Base.mxl tests/gliss_scores/Test2_Gliss.mxl \
  -o text -i notesandrests glissandos

# Everything except glissandos and instruments
python -m musicdiff score1.mscz score2.mscz -o text -x glissandos instruments

# Notation only (skip audiosettings.json and .mscx metadata/style diffs)
python -m musicdiff score1.mscz score2.mscz -o text --no-audio --no-meta

# Custom MusicXML export cache directory
python -m musicdiff score1.mscz score2.mscz -o text --cache-dir /tmp/mxml_cache
```

### 2.6 OMR-ED / OMR-NED Evaluation Mode
```bash
# Single pair OMR-NED JSON
python -m musicdiff tests/gliss_scores/Test2_Base.mxl tests/gliss_scores/Test2_Gliss.mxl -o omrned
```

### 2.7 MuseScore Extraction (`score-extract` / `python -m musicdiff.musescore.extract`)
```bash
# Fast pure-Python metadata + instrumentation + audioSettings JSON (stdout)
python -m musicdiff.musescore.extract \
  /home/shojha/score-algorithms/msczs/tbd-ss-8-12.mscz \
  --meta-only --print-meta

# Extract only audiosettings.json
python -m musicdiff.musescore.extract \
  /home/shojha/score-algorithms/msczs/tbd-ss-8-12.mscz \
  --audio-only -a /tmp/audio.json

# Export MusicXML + metadata JSON + audio JSON
python -m musicdiff.musescore.extract \
  /home/shojha/score-algorithms/msczs/tbd-ss-8-12.mscz \
  -o /tmp/score.musicxml -m /tmp/meta.json -a /tmp/audio.json
```

### 2.8 Score Merge & Cherry-Pick (`score-merge` / `python -m musicdiff.merge`)
```bash
# 3-way merge (fails on conflict unless --strategy is specified)
python -m musicdiff.merge base.mscz ours.mscz theirs.mscz -o /tmp/merged.mscz \
  --conflict-report /tmp/conflicts.json

# 3-way merge with automatic conflict strategy (ours | theirs | base)
python -m musicdiff.merge base.mscz ours.mscz theirs.mscz -o /tmp/merged.mscz --strategy theirs

# Interactive CLI conflict resolution
python -m musicdiff.merge base.mscz ours.mscz theirs.mscz -o /tmp/merged.mscz --interactive

# 2-way selective cherry-pick: copy audio settings from one .mscz onto another
python -m musicdiff.merge --cherry-pick \
  /home/shojha/score-algorithms/msczs/tbd-ss-8-16.mscz \
  /home/shojha/score-algorithms/msczs/tbd-ss-8-12.mscz \
  -o /tmp/patched_audio.mscz --layers audio

# 2-way selective cherry-pick: copy measures 12-16 of staff 1 + style
python -m musicdiff.merge --cherry-pick src.mscz dst.mscz -o /tmp/patched.mscz \
  --measures 12-16 --staff 1 --layers style
```

---

## 3. Python API Modalities

### 3.1 Unified Structured Diff (`diff_scores`) + PDF Rendering
```python
from pathlib import Path
from musicdiff import DetailLevel, diff_scores

res = diff_scores(
    "/home/shojha/score-algorithms/msczs/tbd-ss-8-12.mscz",
    "/home/shojha/score-algorithms/msczs/tbd-ss-8-16.mscz",
    out_path1=Path("/tmp/s1_diff.pdf"),
    out_path2=Path("/tmp/s2_diff.pdf"),
    visualize_diffs=True,
    detail=DetailLevel.Default,  # includes Glissandos & Instruments
    include_notation=True,
    include_audio=True,
    include_meta=True,
)

print("Has changes:", res.has_changes)
print("Notation cost:", res.notation_cost)
print("Notation ops:", len(res.notation_ops))
print(res.format_text())
payload = res.to_dict()  # JSON-serializable dict
```

### 3.2 Classic `musicdiff.diff()` (Drop-In Backward Compatible, Now Supports `.mscz`/`.mscx`)
```python
from musicdiff import DetailLevel, diff

cost = diff(
    "tests/gliss_scores/Test2_Base.mxl",
    "tests/gliss_scores/Test2_Gliss.mxl",
    out_path1="/tmp/base.pdf",
    out_path2="/tmp/gliss.pdf",
    visualize_diffs=True,
    print_text_output=True,
    print_omr_ned_output=True,
    detail=DetailLevel.AllObjects | DetailLevel.Style,
)
print("Total edit distance cost:", cost)
```

### 3.3 Glissando & Instrument Filtering via `DetailLevel`
```python
from musicdiff import DetailLevel, diff_scores

# Only compare glissandos and instruments on top of notes/rests
detail = DetailLevel.NotesAndRests | DetailLevel.Glissandos | DetailLevel.Instruments
res = diff_scores(
    "tests/gliss_scores/Test2_Base.mxl",
    "tests/gliss_scores/Test2_Gliss.mxl",
    detail=detail,
    include_audio=False,
    include_meta=False,
)
print(res.notation_text)
```

### 3.4 Pure-Python MuseScore Decomposition & Proprietary Diffs
```python
from musicdiff import (
    MuseScoreArchive,
    diff_audio_settings,
    diff_musescore_metadata,
    export_musicxml,
    extract_audio_settings,
    extract_metadata,
    format_audio_diff,
    format_meta_diff,
)

mscz1 = "/home/shojha/score-algorithms/msczs/tbd-ss-8-12.mscz"
mscz2 = "/home/shojha/score-algorithms/msczs/tbd-ss-8-16.mscz"

# In-memory archive inspection
arch = MuseScoreArchive.load(mscz1)
meta = arch.extract_metadata()
print("Title:", meta["metadata"].get("workTitle"))
print("Parts:", len(meta["instrumentation"]))

# Proprietary diffs (pure Python, instant)
audio_res = diff_audio_settings(mscz1, mscz2)
print(format_audio_diff(audio_res))

meta_res = diff_musescore_metadata(mscz1, mscz2)
print(format_meta_diff(meta_res))

# Explicit MusicXML export via MuseScore CLI
xml_path = export_musicxml(mscz1, "/tmp/tbd-ss-8-12.musicxml")
```

### 3.5 3-Way Merge, Custom Conflict Resolver & 2-Way Cherry-Pick
```python
from musicdiff import cherry_pick_scores, merge_scores

# 3-way merge with programmatic conflict resolver
def prefer_ours_for_audio(conflict):
    if conflict.layer == "audio":
        return "ours"
    return "unresolved"

merge_res = merge_scores(
    "base.mscz",
    "ours.mscz",
    "theirs.mscz",
    output_path="/tmp/merged.mscz",
    strategy="fail",
    resolver=prefer_ours_for_audio,
)
print(merge_res.format_report())

# 2-way selective cherry-pick
pick_res = cherry_pick_scores(
    source="/home/shojha/score-algorithms/msczs/tbd-ss-8-16.mscz",
    target="/home/shojha/score-algorithms/msczs/tbd-ss-8-12.mscz",
    output_path="/tmp/cherry_picked.mscz",
    layers=("audio", "style"),
    measure_range=(1, 4),
    staff_id="1",
)
print(pick_res.format_report())
```
