"""Prepare explicitly isolated local recordings for the known-stem benchmark.

Decoding/resampling happens once, before creating ground truth. Scoring remains
unaltered. No separator, model download, source upload or automatic labeling.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

import numpy as np
from scipy.io import wavfile

from cinematic_separation import sha256
from separation_benchmark import (BenchmarkError, MAX_CASES, MAX_SECONDS,
                                  REFERENCE_KINDS, _bundle, _json, _write_json,
                                  build_corpus)
from separation_metrics import ROLES
from video_music import executable


PREPARATION_VERSION = "nexpt-reference-import-v1"
EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".aif", ".aiff", ".ogg", ".opus", ".mp4", ".mov"}
# Disallow network/playlist/concat inputs even when renamed with a media suffix.
INPUT_OPTIONS = ["-protocol_whitelist", "file,pipe", "-format_whitelist", "wav,mp3,mov,flac,aiff,ogg"]
MAX_SOURCE_BYTES = 2 * 1024 ** 3


def _keys(value: dict, allowed: set[str], label: str) -> None:
    if set(value) - allowed:
        raise BenchmarkError(f"Unbekannte Felder in {label}: {sorted(set(value) - allowed)}")


def _number(value: Any, label: str, low: float, high: float) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not low <= value <= high):
        raise BenchmarkError(f"{label} muss endlich und zwischen {low} und {high} sein")
    return float(value)


def _frames(seconds: float, rate: int) -> int:
    """One declared rounding rule for durations, seeks and placement offsets."""
    return math.floor(seconds * rate + .5)


def _run(command: list[str], *, timeout: float) -> bytes:
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BenchmarkError(f"Referenz-Dekodierung fehlgeschlagen: {exc}") from exc
    if result.returncode:
        raise BenchmarkError("Referenz-Dekodierung fehlgeschlagen: "
                             + result.stderr.decode("utf-8", errors="replace")[-1200:])
    return result.stdout


def _toolchain() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    paths, identity = {}, {}
    for name in ("ffmpeg", "ffprobe"):
        path = Path(executable(name)).resolve()
        paths[name] = str(path)
        version = _run([str(path), "-version"], timeout=10).decode("utf-8", errors="replace").splitlines()
        if not version:
            raise BenchmarkError(f"{name} meldet keine Version")
        identity[name] = {"version": version[0], "executable_sha256": sha256(path)}
    return paths, identity


def _probe(source: Path, stream: int, tools: dict[str, str]) -> dict[str, Any]:
    payload = json.loads(_run([
        tools["ffprobe"], "-v", "error", *INPUT_OPTIONS,
        "-select_streams", f"a:{stream}", "-show_entries", "stream=sample_rate,channels,codec_name",
        "-of", "json", str(source)], timeout=15))
    rows = payload.get("streams")
    if not isinstance(rows, list) or len(rows) != 1:
        raise BenchmarkError(f"Deklarierte Audiospur {stream} fehlt: {source.name}")
    row = rows[0]
    channels, rate = int(row.get("channels", 0)), int(row.get("sample_rate", 0))
    if channels not in (1, 2) or not 8_000 <= rate <= 192_000:
        raise BenchmarkError("Referenzquelle braucht Mono/Stereo mit 8–192 kHz; kein automatischer Surround-Downmix")
    return {"codec": row.get("codec_name"), "sample_rate": rate, "channels": channels}


def _decode(source: Path, *, stream: int, start_frame: int, frames: int, rate: int,
            metadata: dict, tools: dict[str, str], timeout: float) -> np.ndarray:
    filters = [f"aresample={rate}", f"atrim=end_sample={frames}", "asetpts=PTS-STARTPTS"]
    if metadata["channels"] == 1:
        # Duplicate mono at unchanged amplitude, rather than a -3 dB pan law.
        filters.append("pan=stereo|c0=c0|c1=c0")
    raw = _run([
        tools["ffmpeg"], "-nostdin", "-hide_banner", "-v", "error", "-threads", "1",
        *INPUT_OPTIONS, "-ss", f"{start_frame / rate:.12f}", "-i", str(source),
        "-map", f"0:a:{stream}", "-vn", "-sn", "-dn",
        "-af", ",".join(filters), "-t", f"{frames / rate:.12f}",
        "-ar", str(rate), "-ac", "2", "-acodec", "pcm_f32le", "-f", "f32le", "pipe:1"],
        timeout=timeout)
    if len(raw) != frames * 2 * 4:
        raise BenchmarkError("Ausschnitt ist zu kurz oder Dekodierung nicht samplegenau; "
                             "Start/Dauer pruefen. Fehlende Quellsamples werden nicht aufgefuellt.")
    audio = np.frombuffer(raw, dtype="<f4").reshape(frames, 2).copy()
    if not np.isfinite(audio).all() or np.max(np.abs(audio)) > 1e6:
        raise BenchmarkError("Dekodierte Quelle enthaelt ungueltige Samples")
    return audio


def _plan(spec: Any, root: Path) -> tuple[int, list[dict[str, Any]]]:
    if (not isinstance(spec, dict) or spec.get("schema_version") != 1
            or spec.get("kind") != "nexpt-reference-import"
            or not isinstance(spec.get("cases"), list) or not 1 <= len(spec["cases"]) <= MAX_CASES):
        raise BenchmarkError("Import braucht schema_version 1, kind nexpt-reference-import und 1–20 cases")
    _keys(spec, {"schema_version", "kind", "sample_rate", "cases"}, "Import")
    rate = spec.get("sample_rate", 44_100)
    if type(rate) is not int or not 8_000 <= rate <= 96_000:
        raise BenchmarkError("Ziel-Samplerate muss eine ganze Zahl zwischen 8000 und 96000 sein")
    cases, seen = [], set()
    for case in spec["cases"]:
        if not isinstance(case, dict):
            raise BenchmarkError("Import-Case muss ein Objekt sein")
        _keys(case, {"id", "reference_kind", "duration_seconds", "mix_gain", "stems"}, "Case")
        identifier = case.get("id")
        if (not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", identifier)
                or identifier in seen):
            raise BenchmarkError("Case-IDs muessen eindeutig und dateisystemsicher sein")
        seen.add(identifier)
        kind = case.get("reference_kind")
        if not isinstance(kind, str) or kind not in REFERENCE_KINDS:
            raise BenchmarkError("Isolierte Aufnahmen oder synthetische Diagnostik explizit deklarieren; keine geschaetzten Stems")
        seconds = _number(case.get("duration_seconds"), "Case-Dauer", 1, MAX_SECONDS)
        count = _frames(seconds, rate)
        gain = _number(case.get("mix_gain", 1), "mix_gain", 0, 1)
        if gain == 0:
            raise BenchmarkError("mix_gain muss groesser als 0 sein")
        stems = case.get("stems")
        if not isinstance(stems, dict) or set(stems) != set(ROLES) or all(v is None for v in stems.values()):
            raise BenchmarkError("music/dialogue/sfx erforderlich, mindestens eine Quelle; null bedeutet bewusste Stille")
        planned = {}
        for role in ROLES:
            entry = stems[role]
            if entry is None:
                planned[role] = None
                continue
            if not isinstance(entry, dict) or any(not isinstance(entry.get(key), str) or not entry[key].strip()
                                                   for key in ("path", "license", "attribution")):
                raise BenchmarkError("Jede Quelle braucht path, license und attribution")
            _keys(entry, {"path", "license", "attribution", "audio_stream", "start_seconds",
                          "duration_seconds", "offset_seconds"}, "Quelle")
            source = (root / Path(entry["path"]).expanduser()).resolve()
            if not source.is_file() or source.suffix.lower() not in EXTENSIONS or source.stat().st_size > MAX_SOURCE_BYTES:
                raise BenchmarkError("Quelle muss eine lokale unterstuetzte Mediendatei bis 2 GiB sein")
            stream = entry.get("audio_stream", 0)
            if type(stream) is not int or not 0 <= stream <= 63:
                raise BenchmarkError("audio_stream muss eine ganze Zahl zwischen 0 und 63 sein")
            start = _number(entry.get("start_seconds", 0), "Quellstart", 0, 86_400)
            duration = _number(entry.get("duration_seconds"), "Ausschnittdauer", 0, MAX_SECONDS)
            offset = _number(entry.get("offset_seconds", 0), "Timeline-Offset", 0, seconds)
            frames, offset_frames = _frames(duration, rate), _frames(offset, rate)
            if frames < 1 or offset_frames + frames > count:
                raise BenchmarkError("Ausschnitt muss mindestens ein Sample lang sein und ganz in die Timeline passen")
            planned[role] = {"source": source, "audio_stream": stream,
                             "license": entry["license"], "attribution": entry["attribution"],
                             "start_seconds": start, "duration_seconds": duration, "offset_seconds": offset,
                             "start_frame": _frames(start, rate), "frames": frames, "offset_frames": offset_frames}
        cases.append({"id": identifier, "reference_kind": kind, "duration_seconds": seconds,
                      "frames": count, "mix_gain": gain, "stems": planned})
    return rate, cases


def prepare_corpus(spec_path: Path, destination: Path, *, decode_timeout: float = 60) -> dict[str, Any]:
    """Compose bounded excerpts and pass exact aligned references to the builder."""
    timeout = _number(decode_timeout, "Dekodier-Zeitlimit", 1, 600)
    spec_path = spec_path.expanduser().resolve()
    spec_hash = sha256(spec_path)
    rate, cases = _plan(_json(spec_path), spec_path.parent)
    originals = {entry["source"]: sha256(entry["source"])
                 for case in cases for entry in case["stems"].values() if entry is not None}
    with _bundle(destination) as bundle:
        tools, tool_identity = _toolchain()
        identity = {"version": PREPARATION_VERSION, "implementation_sha256": sha256(Path(__file__)),
                    "spec_sha256": spec_hash, "tools": tool_identity, "sample_rate": rate,
                    "channels": 2, "rounding": "nearest-frame-half-up",
                    "mono_policy": "duplicate-at-unchanged-amplitude", "normalization": "none",
                    "source_labels_verified": False, "cases": []}
        build_spec = {"schema_version": 1, "cases": []}
        with tempfile.TemporaryDirectory(prefix="reference-sources-", dir=bundle) as temporary:
            work = Path(temporary)
            for case in cases:
                stems, audit = {}, {}
                for role, entry in case["stems"].items():
                    if entry is None:
                        stems[role], audit[role] = None, {"declared_absent": True}
                        continue
                    source = entry["source"]
                    metadata = _probe(source, entry["audio_stream"], tools)
                    clip = _decode(source, stream=entry["audio_stream"], start_frame=entry["start_frame"],
                                   frames=entry["frames"], rate=rate, metadata=metadata, tools=tools, timeout=timeout)
                    timeline = np.zeros((case["frames"], 2), dtype=np.float32)
                    offset = entry["offset_frames"]
                    timeline[offset:offset + len(clip)] = clip
                    filename = f"{case['id']}-{role}.wav"
                    wavfile.write(work / filename, rate, timeline)
                    stems[role] = {"path": filename, "license": entry["license"], "attribution": entry["attribution"]}
                    audit[role] = {k: v for k, v in entry.items() if k != "source"}
                    audit[role].update({"input_sha256": originals[source], "input_format": metadata,
                                        "prepared_sha256": sha256(work / filename), "declared_absent": False,
                                        "leading_silence_frames": offset,
                                        "trailing_silence_frames": case["frames"] - offset - len(clip)})
                build_spec["cases"].append({"id": case["id"], "reference_kind": case["reference_kind"],
                                             "mix_gain": case["mix_gain"], "stems": stems})
                identity["cases"].append({"id": case["id"], "duration_seconds": case["duration_seconds"],
                                           "frames": case["frames"], "stems": audit})
            _write_json(work / "build.json", build_spec)
            corpus = build_corpus(work / "build.json", bundle / "corpus", preparation=identity)
        # Bind original bytes and tools to the corpus before publishing anything.
        if (sha256(spec_path) != spec_hash or any(sha256(p) != h for p, h in originals.items())
                or any(sha256(Path(tools[name])) != data["executable_sha256"] for name, data in tool_identity.items())
                or sha256(Path(__file__)) != identity["implementation_sha256"]):
            raise BenchmarkError("Quelle, Spezifikation oder Import-Werkzeug wurde waehrend des Imports geaendert")
        for child in (bundle / "corpus").iterdir():
            child.rename(bundle / child.name)
        (bundle / "corpus").rmdir()
    return corpus
