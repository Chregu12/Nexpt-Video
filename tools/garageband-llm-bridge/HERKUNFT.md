# Herkunft dieses Ordners

Dieser Ordner ist **keine eigene Arbeit**. Er ist eine wortgetreue Kopie
(Vendoring) eines fremden Projekts:

| | |
|---|---|
| Projekt | [`extao15/garageband-llm-bridge`](https://github.com/extao15/garageband-llm-bridge) |
| Stand | `f3d12e8b24886964a488ab3db705b475d2e25bf1` — *Add MusicXML harmony accompaniment*, 14.06.2026 |
| Lizenz | MIT — siehe [`LICENSE`](./LICENSE), Copyright (c) 2026 GarageBand LLM Bridge contributors |
| Kopiert am | 30.08.2026 |

**Unverändert.** Beim Kopieren wurde jede Datei per SHA-256 gegen den Klon des
Upstream-Repositories geprüft: 103 Dateien, keine fehlt, keine ist zu viel,
keine weicht inhaltlich ab. Einzige Ergänzung ist diese Datei.

Die MIT-Lizenz erlaubt das Kopieren ausdrücklich und verlangt dafür, dass
Copyright-Vermerk und Lizenztext erhalten bleiben. Beides liegt in `LICENSE`
und darf nicht entfernt werden.

## Warum kopiert und nicht als Submodul

Zuerst hing der Ordner als Git-Submodul am Upstream-Repository. Das wäre der
sauberere Weg, setzt aber einen eigenen Fork voraus, damit das Projekt nicht an
einem fremden Repository hängt, das sich unter uns ändern kann. Der Fork liess
sich aus der Arbeitsumgebung heraus nicht anlegen. Statt ein Submodul auf ein
fremdes Repository zeigen zu lassen, liegen die Dateien jetzt direkt hier — ein
Klon weniger, den jemand vergessen kann zu initialisieren.

## Wenn Upstream sich weiterentwickelt

Es gibt keine automatische Aktualisierung. Ein neuer Stand kommt so herein:

```bash
git clone --depth 1 https://github.com/extao15/garageband-llm-bridge /tmp/gb-neu
rm -rf tools/garageband-llm-bridge
mkdir -p tools/garageband-llm-bridge
tar cf - -C /tmp/gb-neu --exclude=.git . | tar xf - -C tools/garageband-llm-bridge
# HERKUNFT.md neu schreiben: Commit, Datum, Zahl der Dateien
```

Danach `python3 garageband/compose.py --midi` laufen lassen — es prüft die
Partitur gegen das Score-Spec der Bridge und meldet, wenn sich das Format
geändert hat.

## Was hier NICHT geändert werden darf

Alles in diesem Ordner. Wer an der Bridge etwas anpasst, kann nicht mehr
aktualisieren, ohne die Änderung von Hand nachzuziehen. NEXPT-spezifischer Code
gehört nach `garageband/` — siehe [`../../garageband/README.md`](../../garageband/README.md).
