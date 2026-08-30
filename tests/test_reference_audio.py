from __future__ import annotations

import sys
import tempfile
import unittest
import wave
import json
from pathlib import Path

import numpy as np


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/"render"))

from audio_common import write_pcm24  # noqa: E402
from music_reference import compose  # noqa: E402
from reference_analyzer import analyze_reference  # noqa: E402
from reference_compare import similarity_report  # noqa: E402
from reference_drums import ReferenceDrumFactory, create_sound_factory  # noqa: E402
from reference_sound import ReferenceSoundFactory  # noqa: E402


SR = 48_000
BPM = 118.0
SIXTEENTH = 60/BPM/4
BAR = SIXTEENTH*16


def add(buffer: np.ndarray, sound: np.ndarray, moment: float, pan: float) -> None:
    start = int(round(moment*SR))
    count = min(len(sound), len(buffer)-start)
    if count <= 0:
        return
    left, right = np.cos(pan*np.pi/2), np.sin(pan*np.pi/2)
    buffer[start:start+count, 0] += sound[:count]*left
    buffer[start:start+count, 1] += sound[:count]*right


def synthetic_reference(bars: int = 8) -> np.ndarray:
    rng = np.random.default_rng(17)
    audio = np.zeros((int(round(bars*BAR*SR)), 2), dtype=np.float64)

    def low() -> np.ndarray:
        t = np.arange(int(.34*SR))/SR
        frequency = 72+54*np.exp(-t*26)
        phase = 2*np.pi*np.cumsum(frequency)/SR
        return np.sin(phase)*np.exp(-t*10)

    def body(pitch: float) -> np.ndarray:
        t = np.arange(int(.17*SR))/SR
        return (np.sin(2*np.pi*pitch*t)+.35*np.sin(2*np.pi*pitch*1.71*t)) \
            * np.exp(-t*28)

    def tick(seed: int) -> np.ndarray:
        local = np.random.default_rng(seed)
        t = np.arange(int(.065*SR))/SR
        noise = local.standard_normal(len(t))
        # Differenz filtert tiefe Anteile ohne zusaetzliche Testabhaengigkeit.
        noise = np.r_[noise[0], np.diff(noise)]
        return noise*np.exp(-t*75)*.22

    for bar in range(bars):
        add(audio, low(), bar*BAR, .5)
        if bar % 2:
            add(audio, low()*.67, bar*BAR+10*SIXTEENTH, .5)
        for index, position in enumerate((3, 11)):
            jitter = (.006 if position == 11 else -.004)+(bar % 3-1)*.001
            add(audio, body(760+index*420), bar*BAR+position*SIXTEENTH+jitter,
                .34 if index == 0 else .66)
        for position in (5, 9, 13, 15):
            add(audio, tick(bar*31+position), bar*BAR+position*SIXTEENTH+.003, .22+.56*rng.random())
    peak = np.max(np.abs(audio)) or 1.0
    return (audio/peak*.52).astype(np.float32)


def write_wav(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes((np.clip(audio, -1, 1)*32767).astype("<i2").tobytes())


def write_mono_wav(path: Path, audio: np.ndarray, rate: int = SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes((np.clip(audio, -1, 1)*32767).astype("<i2").tobytes())


def centroid(audio: np.ndarray) -> float:
    power = np.abs(np.fft.rfft(audio*np.hanning(len(audio))))**2
    frequencies = np.fft.rfftfreq(len(audio), 1/SR)
    return float((power*frequencies).sum()/(power.sum()+1e-20))


class ReferenceAudioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.source = Path(cls.temp.name)/"synthetic-reference.wav"
        write_wav(cls.source, synthetic_reference())
        cls.profile = analyze_reference(
            cls.source, bpm_hint=BPM, downbeat_hint=0.0,
            include_events=True, ebu=False,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_profile_contains_reusable_descriptors(self) -> None:
        profile = self.profile
        self.assertEqual(profile["schema_version"], 1)
        self.assertAlmostEqual(profile["tempo"]["bpm"], BPM, places=3)
        self.assertEqual(profile["arrangement"]["bars"], 8)
        self.assertGreater(profile["method"]["event_count"], 30)
        self.assertGreaterEqual(len(profile["sound_families"]), 3)
        self.assertEqual(len(profile["groove"]["positions"]), 16)
        self.assertEqual(set(profile["rhythm_model"]["roles"]),
                         {"low", "body", "tonal", "detail"})
        self.assertGreater(profile["rhythm_model"]["events_per_bar"], 3)
        self.assertIn("sha256", profile["source"])

    def test_factory_creates_new_separated_sound_roles(self) -> None:
        factory = ReferenceSoundFactory(self.profile, seed=9)
        low = factory.render("low", 0, .7)
        body = factory.render("body", 1, .7)
        detail = factory.render("detail", 2, .7)
        for sound in (low, body, detail):
            self.assertTrue(np.all(np.isfinite(sound)))
            self.assertGreater(float(np.max(np.abs(sound))), .2)
        self.assertLess(centroid(low), centroid(body))
        self.assertLess(centroid(body), centroid(detail))
        self.assertFalse(np.array_equal(low[:min(len(low), len(body))],
                                        body[:min(len(low), len(body))]))

    def test_real_drum_factory_uses_velocity_layers_and_round_robins(self) -> None:
        library = Path(self.temp.name)/"vcsl-fixture"
        fixture_rate = 44_100
        t = np.arange(int(.42*fixture_rate))/fixture_rate
        rng = np.random.default_rng(31)
        sources = {
            "bass-soft.wav": np.sin(2*np.pi*74*t)*np.exp(-t*10)*.55,
            "bass-hard.wav": np.sin(2*np.pi*91*t)*np.exp(-t*9)*.90,
            "stick-a.wav": np.sin(2*np.pi*2750*t)*np.exp(-t*48)*.72,
            "stick-b.wav": np.sin(2*np.pi*3300*t)*np.exp(-t*54)*.72,
            "bongo-a.wav": np.sin(2*np.pi*520*t)*np.exp(-t*22)*.76,
            "bongo-b.wav": np.sin(2*np.pi*610*t)*np.exp(-t*25)*.76,
            "hat-a.wav": rng.standard_normal(len(t))*np.exp(-t*50)*.22,
            "hat-b.wav": rng.standard_normal(len(t))*np.exp(-t*58)*.22,
        }
        for name, audio in sources.items():
            write_mono_wav(library/name, audio, fixture_rate)
        catalog = {
            "quelle": "test-fixture",
            "lizenz": "CC0 1.0 Universal",
            "artikulationen": {
                "BDrumNew_hit": [
                    {"datei": "bass-soft.wav", "stufe": 1, "rr": 1},
                    {"datei": "bass-hard.wav", "stufe": 2, "rr": 1},
                ],
                "Snare2_stick": [
                    {"datei": "stick-a.wav", "stufe": 1, "rr": 1},
                    {"datei": "stick-b.wav", "stufe": 1, "rr": 2},
                ],
                "Darbuka_2_hit": [
                    {"datei": "bongo-a.wav", "stufe": 1, "rr": 1},
                    {"datei": "bongo-b.wav", "stufe": 1, "rr": 2},
                ],
                "HiHat_HitC": [
                    {"datei": "hat-a.wav", "stufe": 1, "rr": 1},
                    {"datei": "hat-b.wav", "stufe": 1, "rr": 2},
                ],
            },
        }
        (library/"katalog.json").write_text(
            json.dumps(catalog), encoding="utf-8")

        factory = ReferenceDrumFactory(self.profile, library=library, seed=5)
        soft = factory.render("low", 0, .15)
        hard = factory.render("low", 0, .95)
        first = factory.render("body", 0, .65)
        second = factory.render("body", 1, .65)
        for sound in (soft, hard, first, second):
            self.assertTrue(np.all(np.isfinite(sound)))
            self.assertGreater(float(np.max(np.abs(sound))), .15)
        self.assertFalse(np.array_equal(soft, hard))
        self.assertFalse(np.array_equal(first, second))
        selected = create_sound_factory(
            self.profile, sound_source="auto", library=library, seed=5)
        self.assertIsInstance(selected, ReferenceDrumFactory)
        self.assertEqual(selected.describe()["engine"], "real-drum-samples")
        self.assertEqual(selected.describe()["library_license"], "CC0 1.0 Universal")

    def test_short_composition_is_deterministic_and_stemmed(self) -> None:
        stems_a, master_a, events_a, context_a = compose(
            self.profile, 4*BAR, 4, BPM, cues=[], seed=42, tail=.2)
        stems_b, master_b, events_b, context_b = compose(
            self.profile, 4*BAR, 4, BPM, cues=[], seed=42, tail=.2)
        self.assertEqual(set(stems_a), {"low", "body", "tonal", "detail"})
        self.assertGreater(len(events_a), 12)
        self.assertEqual(events_a, events_b)
        self.assertEqual(context_a["seed"], context_b["seed"])
        np.testing.assert_allclose(master_a, master_b, atol=1e-7)
        self.assertLessEqual(float(np.max(np.abs(master_a))), 10**(-3/20)+1e-5)

    def test_four_bar_motif_has_controlled_repetition(self) -> None:
        _, _, events, _ = compose(
            self.profile, 8*BAR, 8, BPM, cues=[], seed=71, tail=.2)
        slots = [(event["bar"], event["position"]) for event in events]
        self.assertEqual(len(slots), len(set(slots)))
        patterns: dict[tuple[int, str], set[int]] = {}
        for event in events:
            patterns.setdefault((event["bar"]-1, event["role"]), set()).add(
                event["position"])
        scores = []
        for bar in range(4):
            for role in ("low", "body", "tonal"):
                first = patterns.get((bar, role), set())
                repeated = patterns.get((bar+4, role), set())
                union = first | repeated
                if union:
                    scores.append(len(first & repeated)/len(union))
        self.assertGreater(float(np.mean(scores)), .34)

    def test_pcm_writer_produces_complete_output(self) -> None:
        path = Path(self.temp.name)/"complete-output.wav"
        audio = np.zeros((SR//2, 2), dtype=np.float32)
        write_pcm24(path, audio)
        self.assertGreaterEqual(path.stat().st_size, len(audio)*2*3)

    def test_comparator_scores_identical_profiles_as_target(self) -> None:
        report = similarity_report(self.profile, self.profile)
        self.assertAlmostEqual(report["overall_score_0_100"], 100.0, places=1)
        self.assertEqual(report["scores_0_100"]["frequency_balance"], 100.0)


if __name__ == "__main__":
    unittest.main()
