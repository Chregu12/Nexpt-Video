"""Image/URL tab extraction helpers."""

from __future__ import annotations

import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from garageband_bridge import tab_midi


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".webp"}


def download_image(url: str, output_dir: str | Path | None = None) -> Path:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Image URL must start with http:// or https://")

    target_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="garageband-tab-image-"))
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        suffix = ".img"
    output = target_dir / f"source-tab{suffix}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "GarageBand-LLM-Bridge/0.1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        output.write_bytes(response.read())
    return output


def recognize_text(image_path: str | Path) -> str:
    image = Path(image_path).expanduser().resolve()
    if not image.exists():
        raise FileNotFoundError(f"Image not found: {image}")
    swift = Path(__file__).with_name("vision_ocr.swift")
    proc = subprocess.run(
        ["swift", str(swift), str(image)],
        text=True,
        capture_output=True,
        timeout=90,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "Vision OCR failed").strip())
    return proc.stdout.strip()


def _normalize_line(line: str) -> str:
    line = line.strip()
    line = line.replace("—", "-").replace("–", "-").replace("―", "-")
    line = line.replace("I", "|").replace("l", "|")
    line = line.replace(" ", "")
    return line


def extract_tab_text(ocr_text: str) -> str:
    """Pull likely six-line guitar tab blocks out of OCR output."""
    candidates: list[str] = []
    tab_chars = r"[-0-9hHpPbBrR/\\~xX|]"
    pattern = re.compile(rf"^([A-Ga-g](?:[#b♯♭])?)[|:]?({tab_chars}+)$")
    continuation = re.compile(rf"^{tab_chars}+$")
    for raw in ocr_text.splitlines():
        line = _normalize_line(raw)
        match = pattern.match(line)
        if not match:
            if candidates and continuation.match(line):
                candidates[-1] = candidates[-1] + re.sub(rf"[^{tab_chars[1:-1]}]", "-", line)
            continue
        label, body = match.groups()
        cleaned_body = re.sub(rf"[^{tab_chars[1:-1]}]", "-", body)
        candidates.append(f"{label}|{cleaned_body}")

    if len(candidates) < 6:
        ordered = _fallback_ordered_tab_lines(ocr_text)
        if ordered:
            candidates = ordered
        else:
            raise ValueError(
                "OCR text did not contain six recognizable guitar-tab lines. "
                "Try a clearer image or pass manually transcribed tab text."
            )
    return "\n".join(candidates[: (len(candidates) // 6) * 6])


def _fallback_ordered_tab_lines(ocr_text: str) -> list[str]:
    """Recover common Vision OCR tab failures by assuming standard six-line order."""
    ordered_labels = ["e", "B", "G", "D", "A", "E"]
    lines: list[str] = []
    tab_like = re.compile(r"^[-0-9hHpPbBrR/\\~xX|A-Ga-g#b♯♭]+$")
    for raw in ocr_text.splitlines():
        line = _normalize_line(raw)
        if len(line) < 4 or not tab_like.match(line) or not any(ch.isdigit() for ch in line):
            continue
        lines.append(line)
    if len(lines) < 6:
        return []
    recovered: list[str] = []
    for label, raw in zip(ordered_labels, lines[:6]):
        body = raw
        if body[:1] in {"e", "B", "G", "D", "A", "E"}:
            body = body[1:]
        elif label in {"e", "G"} and body[:1] in {"0", "6"} and len(body) > 1 and body[1] in {"-", "|", ":"}:
            body = body[1:]
        body = body.lstrip("|:")
        body = re.sub(r"[^-0-9hHpPbBrR/\\~xX|]", "-", body)
        if "|" not in body:
            body = body.rstrip("|")
        recovered.append(f"{label}|{body}")
    return recovered


def image_to_tab_text(image_path: str | Path) -> dict[str, Any]:
    ocr_text = recognize_text(image_path)
    tab_text = extract_tab_text(ocr_text)
    capo = tab_midi.detect_capo(ocr_text)
    tuning = tab_midi.detect_tuning(ocr_text)
    bpm = tab_midi.detect_bpm(ocr_text)
    parsed_notes = tab_midi.parse_guitar_tab(tab_text, capo=capo, tuning=tuning)
    return {
        "image_path": str(Path(image_path).expanduser().resolve()),
        "ocr_text": ocr_text,
        "tab_text": tab_text,
        "capo": capo,
        "tuning": tuning or "standard",
        "bpm": bpm,
        "notes": len(parsed_notes),
    }


def image_url_to_tab_text(url: str, download_dir: str | Path | None = None) -> dict[str, Any]:
    image = download_image(url, download_dir)
    result = image_to_tab_text(image)
    result["source_url"] = url
    return result
