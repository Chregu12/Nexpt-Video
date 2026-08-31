"""Complete instrument taxonomy and installed GarageBand patch inventory.

The taxonomy covers every zero-based General MIDI program plus a small set of
GarageBand world/synth classes. GarageBand patch names are deliberately kept
separate: they depend on the app version, UI language and downloaded Sound
Library packs, so ``session.py inventory`` discovers them on the target Mac.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any, Iterable


FAMILY_DEFINITIONS: dict[str, dict[str, Any]] = {
    "piano": {
        "name": "Pianos", "prompt": "an acoustic or electric keyboard piano",
        "query": "Piano", "roles": ("harmony", "melody"), "range": (21, 108),
    },
    "mallets": {
        "name": "Mallets and Bells", "prompt": "pitched mallets bells or chromatic percussion",
        "query": "Mallet", "roles": ("harmony", "melody"), "range": (36, 108),
    },
    "organ": {
        "name": "Organs", "prompt": "an organ keyboard instrument",
        "query": "Organ", "roles": ("harmony", "melody"), "range": (24, 108),
    },
    "accordion": {
        "name": "Accordion and Harmonica", "prompt": "accordion harmonica or free reed instrument",
        "query": "Accordion", "roles": ("harmony", "melody"), "range": (36, 100),
    },
    "acoustic_guitar": {
        "name": "Acoustic Guitars", "prompt": "an acoustic plucked guitar",
        "query": "Acoustic Guitar", "roles": ("harmony", "melody"), "range": (40, 96),
    },
    "electric_guitar": {
        "name": "Electric Guitars", "prompt": "an amplified electric guitar",
        "query": "Electric Guitar", "roles": ("harmony", "melody"), "range": (40, 100),
    },
    "bass": {
        "name": "Basses", "prompt": "an acoustic electric or synthesizer bass instrument",
        "query": "Bass", "roles": ("bass",), "range": (24, 76),
    },
    "solo_strings": {
        "name": "Solo Strings", "prompt": "a solo bowed or plucked orchestral string instrument",
        "query": "Strings", "roles": ("bass", "harmony", "melody"), "range": (28, 108),
    },
    "string_ensemble": {
        "name": "String Ensembles", "prompt": "an orchestral string ensemble",
        "query": "Strings", "roles": ("harmony", "melody"), "range": (36, 108),
    },
    "choir": {
        "name": "Choirs and Voices", "prompt": "a choir or synthetic vocal ensemble",
        "query": "Choir", "roles": ("harmony", "melody"), "range": (36, 96),
    },
    "orchestra": {
        "name": "Orchestra", "prompt": "a full symphony orchestra hit or ensemble",
        "query": "Orchestra", "roles": ("harmony", "melody"), "range": (24, 108),
    },
    "brass": {
        "name": "Brass", "prompt": "an acoustic or synthesized brass instrument",
        "query": "Brass", "roles": ("harmony", "melody"), "range": (28, 100),
    },
    "reeds": {
        "name": "Reeds", "prompt": "a saxophone oboe bassoon or clarinet",
        "query": "Woodwind", "roles": ("bass", "melody"), "range": (34, 103),
    },
    "pipes": {
        "name": "Flutes and Pipes", "prompt": "a flute pipe whistle or blown woodwind instrument",
        "query": "Flute", "roles": ("melody",), "range": (48, 108),
    },
    "synth_lead": {
        "name": "Synth Leads", "prompt": "an electronic synthesizer lead",
        "query": "Lead", "roles": ("melody",), "range": (24, 108),
    },
    "synth_pad": {
        "name": "Synth Pads", "prompt": "a sustained atmospheric synthesizer pad",
        "query": "Pad", "roles": ("harmony", "melody"), "range": (24, 108),
    },
    "synth_fx": {
        "name": "Synth Textures", "prompt": "an electronic synthesizer texture or sound effect",
        "query": "Synthesizer", "roles": ("harmony", "melody"), "range": (24, 108),
    },
    "world": {
        "name": "World Instruments", "prompt": "a traditional world music instrument",
        "query": "World", "roles": ("bass", "harmony", "melody"), "range": (28, 108),
    },
    "tuned_percussion": {
        "name": "Tuned Percussion", "prompt": "tuned drums or melodic percussion",
        "query": "Percussion", "roles": ("bass", "harmony", "melody"), "range": (24, 100),
    },
    "sound_effects": {
        "name": "Sound Effects", "prompt": "a non-musical sound effect",
        "query": "Sound Effects", "roles": ("melody",), "range": (0, 127),
    },
}


# Official GM Level 1 order. Names are one based in user-facing GM tables;
# their tuple index is the zero-based MIDI program written to the score.
GM_PROGRAM_NAMES = (
    "Acoustic Grand Piano", "Bright Acoustic Piano", "Electric Grand Piano", "Honky-tonk Piano",
    "Electric Piano 1", "Electric Piano 2", "Harpsichord", "Clavinet",
    "Celesta", "Glockenspiel", "Music Box", "Vibraphone",
    "Marimba", "Xylophone", "Tubular Bells", "Dulcimer",
    "Drawbar Organ", "Percussive Organ", "Rock Organ", "Church Organ",
    "Reed Organ", "Accordion", "Harmonica", "Tango Accordion",
    "Acoustic Guitar Nylon", "Acoustic Guitar Steel", "Electric Guitar Jazz", "Electric Guitar Clean",
    "Electric Guitar Muted", "Overdriven Guitar", "Distortion Guitar", "Guitar Harmonics",
    "Acoustic Bass", "Electric Bass Finger", "Electric Bass Pick", "Fretless Bass",
    "Slap Bass 1", "Slap Bass 2", "Synth Bass 1", "Synth Bass 2",
    "Violin", "Viola", "Cello", "Contrabass",
    "Tremolo Strings", "Pizzicato Strings", "Orchestral Harp", "Timpani",
    "String Ensemble 1", "String Ensemble 2", "Synth Strings 1", "Synth Strings 2",
    "Choir Aahs", "Voice Oohs", "Synth Voice", "Orchestra Hit",
    "Trumpet", "Trombone", "Tuba", "Muted Trumpet",
    "French Horn", "Brass Section", "Synth Brass 1", "Synth Brass 2",
    "Soprano Sax", "Alto Sax", "Tenor Sax", "Baritone Sax",
    "Oboe", "English Horn", "Bassoon", "Clarinet",
    "Piccolo", "Flute", "Recorder", "Pan Flute",
    "Blown Bottle", "Shakuhachi", "Whistle", "Ocarina",
    "Lead 1 Square", "Lead 2 Sawtooth", "Lead 3 Calliope", "Lead 4 Chiff",
    "Lead 5 Charang", "Lead 6 Voice", "Lead 7 Fifths", "Lead 8 Bass and Lead",
    "Pad 1 New Age", "Pad 2 Warm", "Pad 3 Polysynth", "Pad 4 Choir",
    "Pad 5 Bowed", "Pad 6 Metallic", "Pad 7 Halo", "Pad 8 Sweep",
    "FX 1 Rain", "FX 2 Soundtrack", "FX 3 Crystal", "FX 4 Atmosphere",
    "FX 5 Brightness", "FX 6 Goblins", "FX 7 Echoes", "FX 8 Sci-Fi",
    "Sitar", "Banjo", "Shamisen", "Koto",
    "Kalimba", "Bagpipe", "Fiddle", "Shanai",
    "Tinkle Bell", "Agogo", "Steel Drums", "Woodblock",
    "Taiko Drum", "Melodic Tom", "Synth Drum", "Reverse Cymbal",
    "Guitar Fret Noise", "Breath Noise", "Seashore", "Bird Tweet",
    "Telephone Ring", "Helicopter", "Applause", "Gunshot",
)


PROGRAM_KEY_OVERRIDES = {
    0: "piano", 4: "electric_piano", 12: "marimba", 19: "organ",
    25: "acoustic_guitar", 27: "electric_guitar", 33: "bass",
    40: "violin", 42: "cello", 46: "harp", 48: "strings",
    56: "trumpet", 61: "brass", 66: "saxophone", 71: "clarinet",
    73: "flute", 80: "synth_lead", 89: "synth_pad",
}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _family_for_program(program: int) -> str:
    if program <= 7:
        return "piano"
    if program <= 15:
        return "mallets"
    if program <= 20:
        return "organ"
    if program <= 23:
        return "accordion"
    if program <= 25:
        return "acoustic_guitar"
    if program <= 31:
        return "electric_guitar"
    if program <= 39:
        return "bass"
    if program <= 46:
        return "solo_strings"
    if program == 47:
        return "tuned_percussion"
    if program <= 51:
        return "string_ensemble"
    if program <= 54:
        return "choir"
    if program == 55:
        return "orchestra"
    if program <= 63:
        return "brass"
    if program <= 71:
        return "reeds"
    if program <= 79:
        return "pipes"
    if program <= 87:
        return "synth_lead"
    if program <= 95:
        return "synth_pad"
    if program <= 103:
        return "synth_fx"
    if program <= 111:
        return "world"
    if program <= 119:
        return "tuned_percussion"
    return "sound_effects"


PATCH_OVERRIDES: dict[str, dict[str, Any]] = {
    "piano": {"query": "Piano", "preferred": ["Steinway Grand Piano", "Classical Grand", "Grand Piano"]},
    "electric_piano": {"query": "Electric Piano", "preferred": ["Classic Electric Piano", "Vintage Electric Piano"]},
    "violin": {"query": "Violin", "preferred": ["Violin", "Solo Violin"]},
    "cello": {"query": "Cello", "preferred": ["Cello", "Solo Cello"]},
    "strings": {"query": "Strings", "preferred": ["Studio Strings", "String Ensemble", "Hollywood Strings"]},
    "acoustic_guitar": {"query": "Acoustic Guitar", "preferred": ["Natural Acoustic", "Steel String Acoustic", "Acoustic Guitar"]},
    "electric_guitar": {"query": "Electric Guitar", "preferred": ["Clean Electric Guitar", "Classic Clean", "Brit and Clean"]},
    "bass": {"query": "Bass", "preferred": ["Liverpool Bass", "Picked Bass", "Fingerstyle Bass"]},
    "organ": {"query": "Organ", "preferred": ["Classic Rock Organ", "Church Organ"]},
    "flute": {"query": "Flute", "preferred": ["Flute", "Concert Flute"]},
    "clarinet": {"query": "Clarinet", "preferred": ["Clarinet"]},
    "saxophone": {"query": "Saxophone", "preferred": ["Tenor Sax", "Alto Sax", "Saxophone"]},
    "trumpet": {"query": "Trumpet", "preferred": ["Trumpet", "Solo Trumpet"]},
    "brass": {"query": "Brass", "preferred": ["Brass Ensemble", "Studio Horns"]},
    "harp": {"query": "Harp", "preferred": ["Harp", "Orchestral Harp"]},
    "marimba": {"query": "Mallet", "preferred": ["Marimba", "Orchestral Marimba"]},
    "synth_lead": {"query": "Lead", "preferred": ["Classic Analog Lead", "Analog Mono"]},
    "synth_pad": {"query": "Pad", "preferred": ["Warm Pad", "Ambient Pad"]},
}


PROMPT_OVERRIDES = {
    "piano": "a solo acoustic grand piano",
    "electric_piano": "a solo vintage electric piano",
    "violin": "a solo acoustic violin", "cello": "a solo acoustic cello",
    "strings": "an orchestral string ensemble",
    "acoustic_guitar": "a solo steel string acoustic guitar",
    "electric_guitar": "a solo electric guitar",
    "bass": "a clean solo electric bass guitar",
    "organ": "a solo tonewheel or pipe organ", "flute": "a solo concert flute",
    "clarinet": "a solo acoustic clarinet", "saxophone": "a solo acoustic saxophone",
    "trumpet": "a solo acoustic trumpet", "brass": "an acoustic orchestral brass section",
    "harp": "a solo acoustic orchestral harp", "marimba": "a solo acoustic marimba",
    "synth_lead": "a monophonic analog synthesizer lead",
    "synth_pad": "a warm sustained synthesizer pad",
}


DISPLAY_OVERRIDES = {
    "piano": "Piano", "electric_piano": "Electric Piano", "bass": "Bass",
    "strings": "Strings", "acoustic_guitar": "Acoustic Guitar",
    "electric_guitar": "Electric Guitar", "organ": "Organ",
    "saxophone": "Saxophone", "brass": "Brass", "harp": "Harp",
    "synth_lead": "Synth Lead", "synth_pad": "Synth Pad",
}


SPECIAL_GARAGEBAND_INSTRUMENTS = (
    ("erhu", "Erhu", 110, "world", "a solo bowed Chinese erhu"),
    ("pipa", "Pipa", 104, "world", "a solo plucked Chinese pipa"),
    ("guzheng", "Guzheng", 107, "world", "a solo plucked Chinese guzheng"),
    ("dizi", "Dizi", 77, "world", "a solo Chinese bamboo dizi flute"),
    ("yangqin", "Yangqin", 15, "world", "a solo Chinese hammered yangqin dulcimer"),
    ("oud", "Oud", 104, "world", "a solo Middle Eastern oud lute"),
    ("qanun", "Qanun", 15, "world", "a solo Middle Eastern qanun zither"),
    ("santoor", "Santoor", 15, "world", "a solo hammered santoor dulcimer"),
    ("ukulele", "Ukulele", 24, "acoustic_guitar", "a solo acoustic ukulele"),
    ("mandolin", "Mandolin", 105, "world", "a solo acoustic mandolin"),
    ("upright_bass", "Upright Bass", 32, "bass", "a solo acoustic upright double bass"),
    ("sub_bass", "Sub Bass", 38, "bass", "a deep electronic sub bass synthesizer"),
    ("synth_pluck", "Synth Pluck", 84, "synth_lead", "a short plucked synthesizer sound"),
    ("synth_arp", "Synth Arpeggiator", 81, "synth_lead", "an arpeggiated electronic synthesizer"),
    ("synth_bell", "Synth Bell", 98, "synth_fx", "an electronic synthesizer bell"),
    ("synth_texture", "Synth Texture", 99, "synth_fx", "an evolving electronic synthesizer texture"),
    ("orchestral_percussion", "Orchestral Percussion", 47, "tuned_percussion", "orchestral timpani and concert percussion"),
)


def _mix_for_family(family: str) -> dict[str, float]:
    if family == "bass":
        return {"volume": .76, "pan": 0, "reverb": .04}
    if family in {"solo_strings", "string_ensemble", "brass", "reeds", "pipes", "orchestra"}:
        return {"volume": .70, "pan": 0, "reverb": .18}
    if family in {"synth_pad", "synth_fx"}:
        return {"volume": .65, "pan": 0, "reverb": .20}
    return {"volume": .70, "pan": 0, "reverb": .12}


def _classifiable(program: int, family: str) -> bool:
    if family in {"choir", "sound_effects"}:
        return False
    if 112 <= program <= 119:
        return program in {114, 116, 117}
    return True


def build_instrument_catalog() -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for program, standard_name in enumerate(GM_PROGRAM_NAMES):
        key = PROGRAM_KEY_OVERRIDES.get(program, _slug(standard_name))
        family = _family_for_program(program)
        family_config = FAMILY_DEFINITIONS[family]
        patch = {
            "query": family_config["query"], "preferred": [standard_name],
            "allow_first": True,
        }
        patch.update(PATCH_OVERRIDES.get(key, {}))
        catalog[key] = {
            "name": DISPLAY_OVERRIDES.get(key, standard_name),
            "instrument": standard_name.casefold(), "program": program,
            "gm_name": standard_name, "family": family,
            "prompt": PROMPT_OVERRIDES.get(key, f"a solo {standard_name.casefold()} instrument"),
            "roles": tuple(family_config["roles"]),
            "range": tuple(family_config["range"]),
            "mix": _mix_for_family(family), "patch": patch,
            "classify": _classifiable(program, family),
            "source_type": "sound_effect" if family == "sound_effects" else "software_instrument",
        }
    for key, name, program, family, prompt in SPECIAL_GARAGEBAND_INSTRUMENTS:
        family_config = FAMILY_DEFINITIONS[family]
        catalog[key] = {
            "name": name, "instrument": name.casefold(), "program": program,
            "gm_name": GM_PROGRAM_NAMES[program], "family": family,
            "prompt": prompt, "roles": tuple(family_config["roles"]),
            "range": tuple(family_config["range"]), "mix": _mix_for_family(family),
            "patch": {
                "query": name, "preferred": [name], "allow_first": True,
            },
            "classify": True, "source_type": "software_instrument",
            "garageband_extension": True,
        }
    return catalog


INSTRUMENT_CATALOG = build_instrument_catalog()


def merge_catalog_overrides(
    overrides: dict[str, dict[str, Any]],
    catalog: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Overlay project-tuned configs without losing taxonomy metadata."""
    merged = deepcopy(catalog or INSTRUMENT_CATALOG)
    for key, override in overrides.items():
        if key not in merged:
            merged[key] = deepcopy(override)
            continue
        patch_override = override.get("patch")
        merged[key].update({
            field: deepcopy(value) for field, value in override.items()
            if field != "patch"
        })
        if isinstance(patch_override, dict):
            merged[key]["patch"].update(deepcopy(patch_override))
    return merged


INSTRUMENT_ALIASES = {
    "klavier": "piano", "grand_piano": "piano", "grand piano": "piano",
    "e-piano": "electric_piano", "electric piano": "electric_piano",
    "geige": "violin", "violine": "violin", "chelo": "cello",
    "streicher": "strings", "string_ensemble": "strings",
    "akustikgitarre": "acoustic_guitar", "acoustic guitar": "acoustic_guitar",
    "gitarre": "acoustic_guitar", "e-gitarre": "electric_guitar",
    "electric guitar": "electric_guitar", "orgel": "organ",
    "floete": "flute", "flöte": "flute", "klarinette": "clarinet",
    "saxofon": "saxophone", "saxophon": "saxophone",
    "trompete": "trumpet", "blechblaeser": "brass", "blechbläser": "brass",
    "harfe": "harp", "synth": "synth_lead", "pad": "synth_pad",
    "kontrabass": "contrabass", "querfloete": "flute", "querflöte": "flute",
    "waldhorn": "french_horn", "posaune": "trombone", "fagott": "bassoon",
    "oboe": "oboe", "bratsche": "viola", "akkordeon": "accordion",
    "mundharmonika": "harmonica", "cembalo": "harpsichord",
}


def classification_keys(catalog: dict[str, dict[str, Any]] | None = None) -> list[str]:
    source = catalog or INSTRUMENT_CATALOG
    return [key for key, config in source.items() if config.get("classify", True)]


def catalog_search_queries(catalog: dict[str, dict[str, Any]] | None = None) -> list[str]:
    source = catalog or INSTRUMENT_CATALOG
    return ["", *list(dict.fromkeys(
        str(config["patch"]["query"]) for config in source.values()
        if config.get("source_type") == "software_instrument"
    ))]


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) > 1 and token not in {"the", "and", "instrument", "solo"}
    }


def _patch_match_score(name: str, config: dict[str, Any]) -> float:
    folded = name.casefold().strip()
    preferred = [str(value).casefold().strip() for value in config["patch"].get("preferred", [])]
    if folded in preferred:
        return 100.0
    if config["name"].casefold() == folded or config.get("gm_name", "").casefold() == folded:
        return 95.0
    score = 0.0
    for candidate in preferred:
        if candidate and (candidate in folded or folded in candidate):
            score = max(score, 72.0)
    target_tokens = _tokens(" ".join([
        str(config["name"]), str(config.get("gm_name", "")),
        *[str(value) for value in config["patch"].get("preferred", [])],
    ]))
    name_tokens = _tokens(name)
    if target_tokens and name_tokens:
        score = max(score, 50.0*len(target_tokens & name_tokens)/len(target_tokens | name_tokens))
    return score


IGNORED_LIBRARY_LABELS = {
    "library", "patch", "patches", "user patches", "instruments",
    "sounds", "search", "missing value",
}


QUERY_DEFAULT_KEYS = {
    "piano": "piano", "electric piano": "electric_piano", "mallet": "marimba",
    "organ": "organ", "accordion": "accordion", "acoustic guitar": "acoustic_guitar",
    "electric guitar": "electric_guitar", "bass": "bass", "violin": "violin",
    "cello": "cello", "strings": "strings", "choir": "choir_aahs",
    "orchestra": "orchestra_hit", "trumpet": "trumpet", "brass": "brass",
    "saxophone": "saxophone", "clarinet": "clarinet", "woodwind": "clarinet",
    "flute": "flute", "harp": "harp", "lead": "synth_lead", "pad": "synth_pad",
    "synthesizer": "synth_texture", "world": "koto", "percussion": "orchestral_percussion",
}


def _result_names(results: Iterable[Any]) -> list[str]:
    names = []
    for result in results:
        value = result.get("name") if isinstance(result, dict) else result
        name = str(value or "").strip()
        if not name or name.casefold() in IGNORED_LIBRARY_LABELS:
            continue
        if name not in names:
            names.append(name)
    return names


def build_patch_inventory(
    searches: list[dict[str, Any]],
    *,
    garageband: dict[str, Any] | None = None,
    catalog: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Map visible Library search results to canonical instrument classes."""
    source = catalog or INSTRUMENT_CATALOG
    by_instrument: dict[str, list[str]] = defaultdict(list)
    by_family: dict[str, list[str]] = defaultdict(list)
    patch_rows = []
    normalized_searches = []
    for search in searches:
        query = str(search.get("query") or "").strip()
        names = _result_names(search.get("results", []))
        normalized_searches.append({
            "query": query, "count": len(names), "results": names,
            **({"error": search["error"]} if search.get("error") else {}),
        })
        candidates = [
            (key, config) for key, config in source.items()
            if (
                not query and config.get("source_type") == "software_instrument"
            ) or str(config["patch"]["query"]).casefold() == query.casefold()
        ]
        for name in names:
            ranked = sorted(
                ((key, _patch_match_score(name, config)) for key, config in candidates),
                key=lambda item: item[1], reverse=True,
            )
            selected = ranked[0][0] if ranked and ranked[0][1] > 0 else None
            confidence = ranked[0][1]/100.0 if ranked else 0.0
            if selected is None and query and candidates:
                # A valid family result without a specific name match remains
                # useful as a fallback for the family's generic instrument.
                default = QUERY_DEFAULT_KEYS.get(query.casefold())
                selected = default if default in dict(candidates) else candidates[0][0]
            if selected and name not in by_instrument[selected]:
                by_instrument[selected].append(name)
            if selected:
                family = str(source[selected]["family"])
                if name not in by_family[family]:
                    by_family[family].append(name)
            patch_rows.append({
                "name": name, "query": query, "instrument": selected,
                "name_match_confidence": round(confidence, 4),
                "candidates": [key for key, _score in ranked[:3]],
            })

    instrument_payload = {}
    for key, names in by_instrument.items():
        instrument_payload[key] = {
            "query": str(source[key]["patch"]["query"]),
            "preferred": names, "allow_first": False,
        }
    family_payload = {}
    for family, names in by_family.items():
        family_payload[family] = {
            "query": str(FAMILY_DEFINITIONS[family]["query"]),
            "preferred": names, "allow_first": False,
        }
    return {
        "schema_version": 1,
        "generator": "garageband/session.py inventory",
        "garageband": garageband or {},
        "taxonomy": {
            "canonical_instruments": len(source),
            "general_midi_programs": len({int(row["program"]) for row in source.values()}),
            "families": len(FAMILY_DEFINITIONS),
        },
        "searches": normalized_searches, "patches": patch_rows,
        "by_instrument": instrument_payload, "by_family": family_payload,
    }


def load_patch_inventory(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.resolve().read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"GarageBand-Inventar existiert nicht: {path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"Ungueltiges GarageBand-Inventar: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("GarageBand-Inventar braucht schema_version 1")
    for field in ("by_instrument", "by_family"):
        patches = payload.get(field, {})
        if not isinstance(patches, dict):
            raise ValueError(f"GarageBand-Inventar {field} muss ein Objekt sein")
        for name, patch in patches.items():
            allowed = INSTRUMENT_CATALOG if field == "by_instrument" else FAMILY_DEFINITIONS
            if name not in allowed:
                raise ValueError(
                    f"GarageBand-Inventar {field} enthaelt unbekannten Schluessel: {name}")
            if not isinstance(patch, dict):
                raise ValueError(
                    f"GarageBand-Inventar {field}.{name} muss ein Objekt sein")
            if not str(patch.get("query") or "").strip():
                raise ValueError(
                    f"GarageBand-Inventar {field}.{name}.query fehlt")
            preferred = patch.get("preferred")
            if (not isinstance(preferred, list) or not preferred or
                    any(not isinstance(value, str) or not value.strip()
                        for value in preferred)):
                raise ValueError(
                    f"GarageBand-Inventar {field}.{name}.preferred muss "
                    "eine nicht-leere String-Liste sein")
            if ("allow_first" in patch and
                    not isinstance(patch["allow_first"], bool)):
                raise ValueError(
                    f"GarageBand-Inventar {field}.{name}.allow_first muss "
                    "Boolean sein")
    payload = deepcopy(payload)
    payload["source_path"] = str(path.resolve())
    return payload


def patch_for_instrument(
    instrument: str,
    inventory: dict[str, Any] | None,
    *,
    catalog: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str]:
    source = catalog or INSTRUMENT_CATALOG
    default = deepcopy(source[instrument]["patch"])
    if not inventory:
        return default, "built-in-catalog"
    exact = inventory.get("by_instrument", {}).get(instrument)
    if isinstance(exact, dict) and exact.get("preferred"):
        return deepcopy(exact), "installed-exact"
    family = str(source[instrument]["family"])
    fallback = inventory.get("by_family", {}).get(family)
    if isinstance(fallback, dict) and fallback.get("preferred"):
        return deepcopy(fallback), "installed-family-fallback"
    return default, "built-in-catalog-no-installed-match"
