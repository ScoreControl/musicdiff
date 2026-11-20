"""Unit and integration tests for consolidated musicdiff + MuseScore diff & merge."""

from __future__ import annotations

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

import music21 as m21

import musicdiff
from musicdiff import (
    DetailLevel,
    MuseScoreArchive,
    cherry_pick_scores,
    diff,
    diff_audio_settings,
    diff_musescore_metadata,
    diff_scores,
    merge_scores,
)


def _make_sample_mscz(
    path: Path,
    *,
    title: str = "Test Score",
    composer: str = "Tester",
    measures_staff1: Optional[List[str]] = None,
    audio_tracks: Optional[List[Dict]] = None,
    style_tags: Optional[Dict[str, str]] = None,
    automation: Optional[Dict] = None,
) -> Path:
    """Builds a minimal valid MuseScore 4 `.mscz` archive for testing."""
    if measures_staff1 is None:
        measures_staff1 = [
            "<Measure><voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord></voice></Measure>",
            "<Measure><voice><Chord><durationType>whole</durationType><Note><pitch>62</pitch></Note></Chord></voice></Measure>",
            "<Measure><voice><Chord><durationType>whole</durationType><Note><pitch>64</pitch></Note></Chord></voice></Measure>",
        ]
    if audio_tracks is None:
        audio_tracks = [
            {
                "partId": "1",
                "instrumentId": "piano",
                "in": {
                    "resourceMeta": {
                        "vendor": "Fluid",
                        "type": "SoundFont",
                        "attributes": {
                            "soundFontName": "MS Basic.sf3",
                            "presetName": "Grand Piano",
                            "presetBank": 0,
                            "presetProgram": 0,
                        },
                    }
                },
                "out": {"volumeDb": 0.0, "pan": 0.0, "muted": False},
            }
        ]
    if style_tags is None:
        style_tags = {"staffDistance": "6.5", "pageWidth": "8.27"}

    mscx_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<museScore version="4.70">\n'
        "  <Score>\n"
        f'    <metaTag name="workTitle">{title}</metaTag>\n'
        f'    <metaTag name="composer">{composer}</metaTag>\n'
        '    <Part id="1">\n'
        "      <trackName>Piano</trackName>\n"
        '      <Instrument id="piano">\n'
        "        <longName>Piano</longName>\n"
        "        <shortName>Pno.</shortName>\n"
        "        <Channel><program value=\"0\"/><synti>Fluid</synti></Channel>\n"
        "      </Instrument>\n"
        "    </Part>\n"
        '    <Staff id="1">\n'
        + "\n".join(f"      {m}" for m in measures_staff1)
        + "\n    </Staff>\n"
        "  </Score>\n"
        "</museScore>\n"
    )

    style_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<museScore version="4.70">\n'
        "  <Style>\n"
        + "\n".join(f"    <{k}>{v}</{k}>" for k, v in style_tags.items())
        + "\n  </Style>\n"
        "</museScore>\n"
    )

    container_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<container><rootfiles>"
        '<rootfile full-path="score.mscx"/>'
        "</rootfiles></container>\n"
    )

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("score.mscx", mscx_xml)
        zf.writestr("audiosettings.json", json.dumps({"tracks": audio_tracks}, indent=2))
        zf.writestr("score_style.mss", style_xml)
        if automation is not None:
            zf.writestr("automation.json", json.dumps(automation, indent=2))
    return path


class TestGlissandoAndInstrumentDiff(unittest.TestCase):
    def test_glissando_add_and_linetype_change(self) -> None:
        base = Path("tests/gliss_scores/Test2_Base.mxl")
        gliss = Path("tests/gliss_scores/Test2_Gliss.mxl")
        changed = Path("tests/gliss_scores/Test2_Gliss_Change.mxl")

        res_add = diff_scores(base, gliss, include_audio=False, include_meta=False)
        self.assertGreater(res_add.notation_cost or 0, 0)
        self.assertIn("Glissando", res_add.notation_text)
        self.assertIn("E4 -> D4", res_add.notation_text)

        res_change = diff_scores(gliss, changed, include_audio=False, include_meta=False)
        self.assertIn("linetype:solid", res_change.notation_text)
        self.assertIn("linetype:wavy", res_change.notation_text)

        # Excluding Glissandos should reduce the cost
        res_no_gliss = diff_scores(
            base,
            gliss,
            detail=DetailLevel.AllObjects & ~DetailLevel.Glissandos,
            include_audio=False,
            include_meta=False,
        )
        self.assertLess(res_no_gliss.notation_cost or 0, res_add.notation_cost or 0)

    def test_part_level_and_mid_score_instrument_diff(self) -> None:
        def _build_score(part_inst: m21.instrument.Instrument, m2_inst: Optional[m21.instrument.Instrument] = None) -> m21.stream.Score:
            sc = m21.stream.Score()
            p = m21.stream.Part(id="P1")
            p.insert(0, part_inst)
            m1 = m21.stream.Measure(number=1)
            m1.append(m21.note.Note("C4", quarterLength=4.0))
            m2 = m21.stream.Measure(number=2)
            if m2_inst is not None:
                m2.insert(0, m2_inst)
            m2.append(m21.note.Note("D4", quarterLength=4.0))
            p.append(m1)
            p.append(m2)
            sc.append(p)
            return sc

        s1 = _build_score(m21.instrument.Piano())
        s2 = _build_score(m21.instrument.Violin())
        res = diff_scores(s1, s2, include_audio=False, include_meta=False)
        self.assertGreater(res.notation_cost or 0, 0)
        self.assertIn("Piano", res.notation_text)
        self.assertIn("Violin", res.notation_text)

        # Turning off DetailLevel.Instruments ignores instrument-only differences
        res_no_inst = diff_scores(
            s1,
            s2,
            detail=DetailLevel.AllObjects & ~DetailLevel.Instruments,
            include_audio=False,
            include_meta=False,
        )
        self.assertEqual(res_no_inst.notation_cost, 0)

        # Mid-score instrument change
        s3 = _build_score(m21.instrument.Flute(), m21.instrument.Clarinet())
        s4 = _build_score(m21.instrument.Flute())
        res_mid = diff_scores(s3, s4, include_audio=False, include_meta=False)
        self.assertGreater(res_mid.notation_cost or 0, 0)
        self.assertIn("Clarinet", res_mid.notation_text)


class TestMuseScoreProprietaryDiffAndMerge(unittest.TestCase):
    def test_proprietary_audio_and_meta_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            s1 = _make_sample_mscz(tdir / "s1.mscz", title="Original", style_tags={"staffDistance": "6.5"})
            s2 = _make_sample_mscz(
                tdir / "s2.mscz",
                title="Revised",
                style_tags={"staffDistance": "7.2"},
                audio_tracks=[
                    {
                        "partId": "1",
                        "instrumentId": "piano",
                        "in": {
                            "resourceMeta": {
                                "vendor": "Muse",
                                "type": "MuseSampler",
                                "attributes": {
                                    "soundFontName": "Muse Keys",
                                    "presetName": "Concert Grand",
                                    "presetBank": 0,
                                    "presetProgram": 1,
                                },
                            }
                        },
                        "out": {"volumeDb": -3.0, "pan": 0.0, "muted": False},
                    }
                ],
            )

            audio_diff = diff_audio_settings(s1, s2)
            self.assertTrue(audio_diff.available)
            self.assertGreater(len(audio_diff.soundfont_changes), 0)
            self.assertGreater(len(audio_diff.mixer_changes), 0)

            meta_diff = diff_musescore_metadata(s1, s2)
            self.assertTrue(meta_diff.available)
            self.assertEqual(len(meta_diff.metadata_changes), 1)
            self.assertEqual(len(meta_diff.style_changes), 1)

    def test_3way_clean_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            m1_base = "<Measure><voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord></voice></Measure>"
            m2_base = "<Measure><voice><Chord><durationType>whole</durationType><Note><pitch>62</pitch></Note></Chord></voice></Measure>"
            m3_base = "<Measure><voice><Chord><durationType>whole</durationType><Note><pitch>64</pitch></Note></Chord></voice></Measure>"

            m1_ours = "<Measure><voice><Chord><durationType>whole</durationType><Note><pitch>61</pitch></Note></Chord></voice></Measure>"
            m3_theirs = "<Measure><voice><Chord><durationType>whole</durationType><Note><pitch>67</pitch></Note></Chord></voice></Measure>"

            base = _make_sample_mscz(tdir / "base.mscz", title="Base", measures_staff1=[m1_base, m2_base, m3_base])
            ours = _make_sample_mscz(
                tdir / "ours.mscz",
                title="Ours Title",
                measures_staff1=[m1_ours, m2_base, m3_base],
                style_tags={"staffDistance": "7.0", "pageWidth": "8.27"},
            )
            theirs = _make_sample_mscz(
                tdir / "theirs.mscz",
                title="Base",
                composer="New Composer",
                measures_staff1=[m1_base, m2_base, m3_theirs],
                audio_tracks=[
                    {
                        "partId": "1",
                        "instrumentId": "piano",
                        "in": {
                            "resourceMeta": {
                                "vendor": "Fluid",
                                "type": "SoundFont",
                                "attributes": {
                                    "soundFontName": "MS Basic.sf3",
                                    "presetName": "Bright Piano",
                                    "presetBank": 0,
                                    "presetProgram": 1,
                                },
                            }
                        },
                        "out": {"volumeDb": -2.5, "pan": 0.0, "muted": False},
                    }
                ],
            )

            out = tdir / "merged.mscz"
            res = merge_scores(base, ours, theirs, out)
            self.assertTrue(res.success, res.format_report())
            self.assertEqual(len(res.conflicts), 0)
            self.assertTrue(out.is_file())

            merged = MuseScoreArchive.load(out)
            meta = merged.extract_metadata()
            self.assertEqual(meta["metadata"]["workTitle"], "Ours Title")
            self.assertEqual(meta["metadata"]["composer"], "New Composer")
            self.assertEqual(merged.audio_settings["tracks"][0]["out"]["volumeDb"], -2.5)

            pitches = [
                el.text
                for el in merged.get_score_element().findall(".//Staff[@id='1']/Measure//Note/pitch")
            ]
            self.assertEqual(pitches, ["61", "62", "67"])

    def test_3way_conflict_detection_and_strategies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            m1_base = "<Measure><voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord></voice></Measure>"
            m1_ours = "<Measure><voice><Chord><durationType>whole</durationType><Note><pitch>65</pitch></Note></Chord></voice></Measure>"
            m1_theirs = "<Measure><voice><Chord><durationType>whole</durationType><Note><pitch>69</pitch></Note></Chord></voice></Measure>"

            base = _make_sample_mscz(tdir / "base.mscz", measures_staff1=[m1_base])
            ours = _make_sample_mscz(tdir / "ours.mscz", measures_staff1=[m1_ours])
            theirs = _make_sample_mscz(tdir / "theirs.mscz", measures_staff1=[m1_theirs])

            # Default fail strategy reports conflict and does not emit output
            fail_out = tdir / "fail.mscz"
            res_fail = merge_scores(base, ours, theirs, fail_out, strategy="fail")
            self.assertFalse(res_fail.success)
            self.assertEqual(len(res_fail.unresolved_conflicts), 1)
            self.assertFalse(fail_out.is_file())

            # Theirs strategy resolves to 69
            theirs_out = tdir / "theirs_win.mscz"
            res_theirs = merge_scores(base, ours, theirs, theirs_out, strategy="theirs")
            self.assertTrue(res_theirs.success)
            merged = MuseScoreArchive.load(theirs_out)
            pitch = merged.get_score_element().findtext(".//Staff[@id='1']/Measure//Note/pitch")
            self.assertEqual(pitch, "69")

    def test_spanner_boundary_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            m1_base = "<Measure><voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord></voice></Measure>"
            m2_base = "<Measure><voice><Chord><durationType>whole</durationType><Note><pitch>62</pitch></Note></Chord></voice></Measure>"
            # Ours opens a cross-measure Slur in M1 (without touching M2)
            m1_ours = (
                "<Measure><voice>"
                '<Spanner type="Slur"><Slur/><next><location><measures>1</measures></location></next></Spanner>'
                "<Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord>"
                "</voice></Measure>"
            )

            base = _make_sample_mscz(tdir / "base.mscz", measures_staff1=[m1_base, m2_base])
            ours = _make_sample_mscz(tdir / "ours.mscz", measures_staff1=[m1_ours, m2_base])
            theirs = _make_sample_mscz(tdir / "theirs.mscz", measures_staff1=[m1_base, m2_base])

            res = merge_scores(base, ours, theirs, tdir / "bad.mscz", strategy="fail")
            self.assertFalse(res.success)
            self.assertTrue(any(c.layer == "spanner" for c in res.conflicts))

    def test_cherry_pick_audio_and_measures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            m1_a = "<Measure><voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord></voice></Measure>"
            m2_a = "<Measure><voice><Chord><durationType>whole</durationType><Note><pitch>62</pitch></Note></Chord></voice></Measure>"
            m1_b = "<Measure><voice><Chord><durationType>whole</durationType><Note><pitch>72</pitch></Note></Chord></voice></Measure>"
            m2_b = "<Measure><voice><Chord><durationType>whole</durationType><Note><pitch>74</pitch></Note></Chord></voice></Measure>"

            src = _make_sample_mscz(
                tdir / "src.mscz",
                measures_staff1=[m1_b, m2_b],
                audio_tracks=[{"partId": "1", "instrumentId": "piano", "out": {"volumeDb": -6.0}}],
            )
            dst = _make_sample_mscz(tdir / "dst.mscz", measures_staff1=[m1_a, m2_a])
            out = tdir / "picked.mscz"

            res = cherry_pick_scores(src, dst, out, layers=("audio",), measure_range=(2, 2), staff_id="1")
            self.assertTrue(res.success)
            merged = MuseScoreArchive.load(out)
            pitches = [
                el.text
                for el in merged.get_score_element().findall(".//Staff[@id='1']/Measure//Note/pitch")
            ]
            self.assertEqual(pitches, ["60", "74"])
            self.assertEqual(merged.audio_settings["tracks"][0]["out"]["volumeDb"], -6.0)


if __name__ == "__main__":
    unittest.main()
