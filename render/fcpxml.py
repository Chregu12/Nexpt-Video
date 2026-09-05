#!/usr/bin/env python3
"""Build a portable Final Cut Pro timeline from ``timing.json``.

The default command keeps the historic video-only behaviour::

    python3 render/fcpxml.py

An explicit audio configuration adds independently editable music and sound-
effect stems as connected clips with Final Cut audio roles::

    python3 render/fcpxml.py --audio-config render/final-cut-audio.json

The generator validates every configured WAV before replacing an existing XML.
It deliberately makes no claim that Final Cut imported the file; that final,
application-level check has to run on a Mac with Final Cut Pro installed.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Sequence
from urllib.parse import quote
import wave
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent
DEFAULT_TIMING = ROOT / "timing.json"
DEFAULT_OUTPUT = ROOT.parent / "out" / "NEXPT-Keynote.fcpxml"
FCPXML_VERSION = "1.10"
EXPECTED_AUDIO_RATE = 48_000
EXPECTED_AUDIO_CHANNELS = 2
MAX_AUDIO_TRACKS = 32

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")
_SAFE_ROLE = re.compile(
    r"^(music|effects)\.[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
)


class FcpxmlError(RuntimeError):
    """Raised when a timeline input cannot be exported safely."""


@dataclass(frozen=True)
class AudioTrack:
    track_id: str
    name: str
    source: Path
    media_url: str
    role: str
    enabled: bool
    lane: int
    channels: int
    sample_rate: int
    sample_width_bits: int
    frames: int
    sha256: str

    @property
    def duration(self) -> Fraction:
        return Fraction(self.frames, self.sample_rate)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FcpxmlError(f"{label} kann nicht gelesen werden: {path}: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FcpxmlError(f"{label} ist kein gueltiges UTF-8-JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise FcpxmlError(f"{label} muss ein JSON-Objekt sein: {path}")
    return payload, _sha256_bytes(raw)


def _require_plain_text(value: Any, label: str, *, maximum: int = 160) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FcpxmlError(f"{label} muss eine nicht leere Zeichenkette sein")
    value = value.strip()
    if len(value) > maximum or any(ord(char) < 32 for char in value):
        raise FcpxmlError(f"{label} ist zu lang oder enthaelt Steuerzeichen")
    return value


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FcpxmlError(f"{label} muss eine Zahl sein")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0) or result < 0:
        qualifier = "positiv und endlich" if positive else "nicht negativ und endlich"
        raise FcpxmlError(f"{label} muss {qualifier} sein")
    return result


def _frame_number(seconds: float, fps: int) -> int:
    """Round non-negative seconds to the closest video frame."""

    return int(math.floor(seconds * fps + 0.5))


def _time(numerator: int, denominator: int = 1) -> str:
    if numerator < 0 or denominator <= 0:
        raise FcpxmlError("Interne FCPXML-Zeit ist ungueltig")
    if numerator == 0:
        return "0s"
    value = Fraction(numerator, denominator)
    if value.denominator == 1:
        return f"{value.numerator}s"
    return f"{value.numerator}/{value.denominator}s"


def _uid(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32].upper()


def _validate_timing(payload: dict[str, Any]) -> dict[str, Any]:
    meta = payload.get("meta")
    scenes = payload.get("scenes")
    if not isinstance(meta, dict) or not isinstance(scenes, list) or not scenes:
        raise FcpxmlError("timing.json braucht ein meta-Objekt und mindestens eine Szene")

    fps = meta.get("fps")
    width = meta.get("width")
    height = meta.get("height")
    if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 120:
        raise FcpxmlError("meta.fps muss eine ganze Zahl zwischen 1 und 120 sein")
    for label, value in (("width", width), ("height", height)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise FcpxmlError(f"meta.{label} muss eine positive ganze Zahl sein")
    title = _require_plain_text(meta.get("title"), "meta.title")

    normalised: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    previous_end = 0
    for index, scene in enumerate(scenes):
        label = f"scenes[{index}]"
        if not isinstance(scene, dict):
            raise FcpxmlError(f"{label} muss ein Objekt sein")
        scene_id = _require_plain_text(scene.get("id"), f"{label}.id", maximum=100)
        if not _SAFE_ID.fullmatch(scene_id):
            raise FcpxmlError(
                f"{label}.id darf nur Buchstaben, Zahlen, _ und - enthalten"
            )
        if scene_id in identifiers:
            raise FcpxmlError(f"Doppelte Szenen-ID: {scene_id}")
        identifiers.add(scene_id)
        act = _require_plain_text(scene.get("act"), f"{label}.act")
        start = _number(scene.get("start"), f"{label}.start")
        duration = _number(scene.get("dur"), f"{label}.dur", positive=True)
        start_frame = _frame_number(start, fps)
        end_frame = _frame_number(start + duration, fps)
        if index == 0 and start_frame != 0:
            raise FcpxmlError("Die erste Szene muss bei 0s beginnen")
        if start_frame < previous_end:
            raise FcpxmlError(
                f"{scene_id} ueberlappt nach dem Frame-Raster die vorherige Szene"
            )
        if end_frame <= start_frame:
            raise FcpxmlError(f"{scene_id} ist kuerzer als ein gerastertes Frame")

        voice = scene.get("vo")
        if voice is not None and not isinstance(voice, str):
            raise FcpxmlError(f"{label}.vo muss eine Zeichenkette sein")

        flips: list[dict[str, str | int]] = []
        raw_flips: list[Any] = []
        if "bgFlip" in scene:
            raw_flips.append(scene["bgFlip"])
        plural = scene.get("bgFlips", [])
        if not isinstance(plural, list):
            raise FcpxmlError(f"{label}.bgFlips muss eine Liste sein")
        raw_flips.extend(plural)
        for flip_index, flip in enumerate(raw_flips):
            flip_label = f"{label}.bgFlips[{flip_index}]"
            if not isinstance(flip, dict):
                raise FcpxmlError(f"{flip_label} muss ein Objekt sein")
            flip_time = _number(flip.get("t"), f"{flip_label}.t")
            if flip_time >= duration:
                raise FcpxmlError(f"{flip_label}.t liegt ausserhalb der Szene")
            target = _require_plain_text(flip.get("to"), f"{flip_label}.to", maximum=80)
            relative_frame = min(
                _frame_number(flip_time, fps), end_frame - start_frame - 1
            )
            flips.append({"frame": relative_frame, "target": target})

        normalised.append(
            {
                "id": scene_id,
                "act": act,
                "start_frame": start_frame,
                "end_frame": end_frame,
                "vo": voice or "",
                "flips": flips,
            }
        )
        previous_end = end_frame

    return {
        "title": title,
        "fps": fps,
        "width": width,
        "height": height,
        "scenes": normalised,
        "visual_end_frame": previous_end,
    }


def _portable_media_url(source: Path, output_parent: Path) -> str:
    try:
        relative = source.relative_to(output_parent.resolve())
    except ValueError as exc:
        raise FcpxmlError(
            f"Audioquelle muss fuer ein portables Paket unter {output_parent} liegen: {source}"
        ) from exc
    return quote(relative.as_posix(), safe="/._-~")


def _inspect_wav(path: Path, label: str) -> dict[str, int]:
    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_rate = source.getframerate()
            sample_width = source.getsampwidth()
            frames = source.getnframes()
            compression = source.getcomptype()
            expected_bytes = frames * channels * sample_width
            read_bytes = 0
            while True:
                block = source.readframes(65_536)
                if not block:
                    break
                read_bytes += len(block)
    except (OSError, EOFError, wave.Error) as exc:
        raise FcpxmlError(f"{label} ist keine lesbare PCM-WAV-Datei: {path}: {exc}") from exc

    if compression != "NONE":
        raise FcpxmlError(f"{label} muss unkomprimiertes PCM enthalten")
    if channels != EXPECTED_AUDIO_CHANNELS:
        raise FcpxmlError(
            f"{label} muss Stereo sein, gefunden: {channels} Kanal/Kanaele"
        )
    if sample_rate != EXPECTED_AUDIO_RATE:
        raise FcpxmlError(
            f"{label} muss 48000 Hz haben, gefunden: {sample_rate} Hz"
        )
    if sample_width not in (2, 3, 4):
        raise FcpxmlError(
            f"{label} braucht 16-, 24- oder 32-Bit-PCM, gefunden: {sample_width * 8} Bit"
        )
    if frames <= 0:
        raise FcpxmlError(f"{label} darf nicht leer sein")
    if read_bytes != expected_bytes:
        raise FcpxmlError(
            f"{label} ist abgeschnitten: Header erwartet {expected_bytes} Audiodaten-Bytes, "
            f"gefunden wurden {read_bytes}"
        )
    return {
        "channels": channels,
        "sample_rate": sample_rate,
        "sample_width_bits": sample_width * 8,
        "frames": frames,
    }


def _load_audio_tracks(
    config_path: Path,
    output_parent: Path,
) -> tuple[list[AudioTrack], str]:
    payload, config_sha256 = _read_json(config_path, "Audio-Konfiguration")
    expected_keys = {"schema_version", "tracks"}
    if set(payload) != expected_keys:
        raise FcpxmlError(
            "Audio-Konfiguration erlaubt genau schema_version und tracks"
        )
    if payload["schema_version"] != 1:
        raise FcpxmlError("Audio-Konfiguration braucht schema_version 1")
    rows = payload["tracks"]
    if not isinstance(rows, list) or not 2 <= len(rows) <= MAX_AUDIO_TRACKS:
        raise FcpxmlError(
            f"Audio-Konfiguration braucht 2 bis {MAX_AUDIO_TRACKS} Tracks"
        )

    tracks: list[AudioTrack] = []
    identifiers: set[str] = set()
    roles: set[str] = set()
    sources: set[Path] = set()
    roots: set[str] = set()
    config_parent = config_path.parent.resolve()
    track_keys = {"id", "name", "path", "role", "enabled"}
    for index, row in enumerate(rows):
        label = f"tracks[{index}]"
        if not isinstance(row, dict) or set(row) != track_keys:
            raise FcpxmlError(
                f"{label} erlaubt genau id, name, path, role und enabled"
            )
        track_id = _require_plain_text(row["id"], f"{label}.id", maximum=100)
        if not _SAFE_ID.fullmatch(track_id):
            raise FcpxmlError(f"{label}.id ist keine sichere Kennung")
        folded_id = track_id.casefold()
        if folded_id in identifiers:
            raise FcpxmlError(f"Doppelte Track-ID: {track_id}")
        identifiers.add(folded_id)

        name = _require_plain_text(row["name"], f"{label}.name", maximum=120)
        role = _require_plain_text(row["role"], f"{label}.role", maximum=72)
        if not _SAFE_ROLE.fullmatch(role):
            raise FcpxmlError(
                f"{label}.role muss music.<subrole> oder effects.<subrole> sein"
            )
        folded_role = role.casefold()
        if folded_role in roles:
            raise FcpxmlError(f"Doppelte Audio-Rolle: {role}")
        roles.add(folded_role)
        roots.add(role.split(".", 1)[0])

        if not isinstance(row["enabled"], bool):
            raise FcpxmlError(f"{label}.enabled muss true oder false sein")
        raw_path = _require_plain_text(row["path"], f"{label}.path", maximum=512)
        configured_path = config_parent / raw_path
        if configured_path.is_symlink():
            raise FcpxmlError(f"{label}.path darf kein Symlink sein: {configured_path}")
        try:
            source = configured_path.resolve(strict=True)
        except OSError as exc:
            raise FcpxmlError(f"{label}.path fehlt: {configured_path}") from exc
        if not source.is_file() or source.suffix.lower() != ".wav":
            raise FcpxmlError(f"{label}.path muss auf eine WAV-Datei zeigen: {source}")
        if source in sources:
            raise FcpxmlError(f"Audioquelle doppelt konfiguriert: {source.name}")
        sources.add(source)
        metadata = _inspect_wav(source, label)
        tracks.append(
            AudioTrack(
                track_id=track_id,
                name=name,
                source=source,
                media_url=_portable_media_url(source, output_parent),
                role=role,
                enabled=row["enabled"],
                lane=-(index + 1),
                sha256=_sha256_file(source),
                **metadata,
            )
        )

    if roots != {"music", "effects"}:
        raise FcpxmlError(
            "Audio-Konfiguration muss mindestens eine music- und eine effects-Rolle enthalten"
        )
    return tracks, config_sha256


def _audio_manifest(track: AudioTrack) -> dict[str, Any]:
    return {
        "id": track.track_id,
        "name": track.name,
        "source": track.media_url,
        "role": track.role,
        "enabled": track.enabled,
        "lane": track.lane,
        "sha256": track.sha256,
        "channels": track.channels,
        "sample_rate": track.sample_rate,
        "sample_width_bits": track.sample_width_bits,
        "frames": track.frames,
        "duration_seconds": round(float(track.duration), 9),
    }


def _build_xml(timing: dict[str, Any], tracks: Sequence[AudioTrack]) -> tuple[str, int]:
    fps = timing["fps"]
    frame_duration = _time(1, fps)
    resources = ET.Element("resources")
    ET.SubElement(
        resources,
        "format",
        {
            "id": "r1",
            "name": f"FFVideoFormat{timing['height']}p{fps}",
            "frameDuration": frame_duration,
            "width": str(timing["width"]),
            "height": str(timing["height"]),
            "colorSpace": "1-1-1 (Rec. 709)",
        },
    )

    for index, scene in enumerate(timing["scenes"], start=1):
        duration_frames = scene["end_frame"] - scene["start_frame"]
        source = f"scenes/{quote(scene['id'], safe='._-~')}.mov"
        asset = ET.SubElement(
            resources,
            "asset",
            {
                "id": f"a{index}",
                "name": scene["id"],
                "uid": _uid(scene["id"]),
                "start": "0s",
                "duration": _time(duration_frames, fps),
                "hasVideo": "1",
                "format": "r1",
                "videoSources": "1",
            },
        )
        ET.SubElement(
            asset,
            "media-rep",
            {
                "kind": "original-media",
                "sig": _uid(source),
                "src": source,
            },
        )

    for index, track in enumerate(tracks, start=1):
        asset = ET.SubElement(
            resources,
            "asset",
            {
                "id": f"aa{index}",
                "name": track.name,
                "uid": _uid(f"audio:{track.sha256}:{track.track_id}"),
                "start": "0s",
                "duration": _time(track.frames, track.sample_rate),
                "hasAudio": "1",
                "audioSources": "1",
                "audioChannels": str(track.channels),
                "audioRate": "48k",
            },
        )
        ET.SubElement(
            asset,
            "media-rep",
            {
                "kind": "original-media",
                "sig": _uid(
                    f"audio-source:{track.track_id}:{track.sha256}"
                ),
                "src": track.media_url,
            },
        )

    root = ET.Element("fcpxml", {"version": FCPXML_VERSION})
    root.append(resources)
    library = ET.SubElement(root, "library", {"name": "NEXPT Video"})
    event = ET.SubElement(library, "event", {"name": "NEXPT Keynote"})
    project = ET.SubElement(event, "project", {"name": timing["title"]})

    longest_audio_frames = max(
        (
            (track.frames * fps + track.sample_rate - 1) // track.sample_rate
            for track in tracks
        ),
        default=0,
    )
    sequence_frames = max(timing["visual_end_frame"], longest_audio_frames)
    sequence = ET.SubElement(
        project,
        "sequence",
        {
            "format": "r1",
            "duration": _time(sequence_frames, fps),
            "tcStart": "0s",
            "tcFormat": "NDF",
            "audioLayout": "stereo",
            "audioRate": "48k",
        },
    )
    spine = ET.SubElement(sequence, "spine")

    cursor = 0
    for index, scene in enumerate(timing["scenes"], start=1):
        start_frame = scene["start_frame"]
        duration_frames = scene["end_frame"] - start_frame
        if start_frame > cursor:
            ET.SubElement(
                spine,
                "gap",
                {
                    "name": "Timing gap",
                    "offset": _time(cursor, fps),
                    "start": "0s",
                    "duration": _time(start_frame - cursor, fps),
                },
            )
        clip = ET.SubElement(
            spine,
            "asset-clip",
            {
                "ref": f"a{index}",
                "offset": _time(start_frame, fps),
                "name": scene["id"],
                "start": "0s",
                "duration": _time(duration_frames, fps),
                "format": "r1",
                "tcFormat": "NDF",
            },
        )
        if index == 1:
            for audio_index, track in enumerate(tracks, start=1):
                ET.SubElement(
                    clip,
                    "asset-clip",
                    {
                        "ref": f"aa{audio_index}",
                        "lane": str(track.lane),
                        "offset": "0s",
                        "name": track.name,
                        "start": "0s",
                        "duration": _time(track.frames, track.sample_rate),
                        "audioRole": track.role,
                        "srcEnable": "audio",
                        "enabled": "1" if track.enabled else "0",
                    },
                )
        ET.SubElement(
            clip,
            "marker",
            {
                "start": "0s",
                "duration": frame_duration,
                "value": f"Akt {scene['act']} · {scene['id']}",
            },
        )
        if scene["vo"]:
            ET.SubElement(
                clip,
                "marker",
                {
                    "start": "0s",
                    "duration": frame_duration,
                    "value": f"VO: {scene['vo']}",
                },
            )
        for flip in scene["flips"]:
            ET.SubElement(
                clip,
                "marker",
                {
                    "start": _time(int(flip["frame"]), fps),
                    "duration": frame_duration,
                    "value": f"BG → {flip['target']}",
                },
            )
        cursor = scene["end_frame"]

    if sequence_frames > cursor:
        ET.SubElement(
            spine,
            "gap",
            {
                "name": "Audio tail",
                "offset": _time(cursor, fps),
                "start": "0s",
                "duration": _time(sequence_frames - cursor, fps),
            },
        )

    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    ET.fromstring(body)
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n{body}\n'
    return xml, sequence_frames


def _stage_text(path: Path, content: str) -> Path:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise FcpxmlError(f"Temporaere Ausgabedatei kann nicht geschrieben werden: {exc}") from exc


def _assert_inputs_unchanged(
    timing_path: Path,
    timing_sha256: str,
    config_path: Path | None,
    config_sha256: str | None,
    tracks: Sequence[AudioTrack],
) -> None:
    try:
        if _sha256_file(timing_path) != timing_sha256:
            raise FcpxmlError("timing.json wurde waehrend des Exports veraendert")
        if config_path is not None and (
            config_sha256 is None or _sha256_file(config_path) != config_sha256
        ):
            raise FcpxmlError("Audio-Konfiguration wurde waehrend des Exports veraendert")
        for track in tracks:
            if _sha256_file(track.source) != track.sha256:
                raise FcpxmlError(
                    f"Audioquelle wurde waehrend des Exports veraendert: {track.source.name}"
                )
    except OSError as exc:
        raise FcpxmlError(
            f"Eine Eingabedatei verschwand waehrend des Exports: {exc}"
        ) from exc


def generate_fcpxml(
    timing_path: Path = DEFAULT_TIMING,
    output_path: Path = DEFAULT_OUTPUT,
    audio_config: Path | None = None,
    *,
    write: bool = True,
) -> dict[str, Any]:
    """Validate inputs, build FCPXML and optionally write it with a manifest."""

    timing_path = Path(timing_path).resolve()
    requested_output = Path(output_path).expanduser()
    if requested_output.is_symlink():
        raise FcpxmlError(f"FCPXML-Ausgabe darf kein Symlink sein: {requested_output}")
    output_path = requested_output.resolve()
    config_path = Path(audio_config).resolve() if audio_config is not None else None
    timing_payload, timing_sha256 = _read_json(timing_path, "Timing-Datei")
    timing = _validate_timing(timing_payload)

    tracks: list[AudioTrack] = []
    config_sha256: str | None = None
    if config_path is not None:
        tracks, config_sha256 = _load_audio_tracks(config_path, output_path.parent)

    xml, sequence_frames = _build_xml(timing, tracks)
    xml_sha256 = _sha256_bytes(xml.encode("utf-8"))
    _assert_inputs_unchanged(
        timing_path, timing_sha256, config_path, config_sha256, tracks
    )

    manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
    result: dict[str, Any] = {
        "schema_version": 1,
        "generator": "render/fcpxml.py",
        "fcpxml_version": FCPXML_VERSION,
        "output": {
            "file": output_path.name,
            "sha256": xml_sha256,
            "manifest": manifest_path.name,
        },
        "inputs": {
            "timing": {"file": timing_path.name, "sha256": timing_sha256},
            "audio_config": (
                {"file": config_path.name, "sha256": config_sha256}
                if config_path is not None
                else None
            ),
        },
        "timeline": {
            "title": timing["title"],
            "fps": timing["fps"],
            "scene_count": len(timing["scenes"]),
            "visual_duration_frames": timing["visual_end_frame"],
            "sequence_duration_frames": sequence_frames,
            "sequence_duration_seconds": round(sequence_frames / timing["fps"], 9),
        },
        "audio": {
            "configured": bool(tracks),
            "track_count": len(tracks),
            "music_and_sfx_separate": (
                {track.role.split(".", 1)[0] for track in tracks}
                == {"music", "effects"}
            ),
            "tracks": [_audio_manifest(track) for track in tracks],
        },
        "verification": {
            "xml_well_formed": True,
            "sources_unchanged": True,
            "final_cut_import_verified": False,
            "note": "Der echte Import muss auf einem Mac mit Final Cut Pro geprueft werden.",
        },
    }

    if write:
        xml_temporary: Path | None = None
        manifest_temporary: Path | None = None
        try:
            xml_temporary = _stage_text(output_path, xml)
            manifest_temporary = _stage_text(
                manifest_path,
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            )
            _assert_inputs_unchanged(
                timing_path, timing_sha256, config_path, config_sha256, tracks
            )
            os.replace(xml_temporary, output_path)
            xml_temporary = None
            os.replace(manifest_temporary, manifest_path)
            manifest_temporary = None
        except OSError as exc:
            raise FcpxmlError(f"FCPXML-Ausgabe kann nicht ersetzt werden: {exc}") from exc
        finally:
            if xml_temporary is not None:
                xml_temporary.unlink(missing_ok=True)
            if manifest_temporary is not None:
                manifest_temporary.unlink(missing_ok=True)

    result["paths"] = {
        "fcpxml": str(output_path),
        "manifest": str(manifest_path),
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timing",
        type=Path,
        default=DEFAULT_TIMING,
        help=f"Timing-JSON (Standard: {DEFAULT_TIMING})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"FCPXML-Ausgabe (Standard: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--audio-config",
        type=Path,
        help="Optionale Konfiguration fuer getrennte Musik- und SFX-Stems",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Alles validieren und XML im Speicher bauen, aber nichts schreiben",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = generate_fcpxml(
            args.timing,
            args.output,
            args.audio_config,
            write=not args.check,
        )
    except FcpxmlError as exc:
        print(f"FCPXML-Fehler: {exc}", file=sys.stderr)
        return 2

    action = "geprueft, nichts geschrieben" if args.check else result["paths"]["fcpxml"]
    print(
        f"{action} · {result['timeline']['scene_count']} Clips · "
        f"{result['audio']['track_count']} Audiospuren · "
        f"{result['timeline']['sequence_duration_seconds']:.2f}s · XML wohlgeformt"
    )
    if not args.check:
        print(f"Manifest: {result['paths']['manifest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
