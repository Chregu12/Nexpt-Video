# Higgsfield Seedance 2.0 Bridge

Dieser Adapter bindet Seedance 2.0 als separaten Cloud-Video-Provider in die
NEXPT-Pipeline ein. Er ersetzt weder Apple Motion noch Final Cut Pro:

1. Seedance erzeugt einen kurzen Ausgangsclip.
2. Der Adapter lädt das MP4 herunter und prüft es per SHA-256.
3. Final Cut importiert den Clip als Source Media.
4. Motion ergänzt kontrollierte Typografie, Compositing und Übergänge.
5. Musik und Soundeffekte bleiben getrennte GarageBand-Stems.

## Offizieller Schnittstellenstand

Higgsfield dokumentiert eine serverseitige REST-API mit `Key ID` und `Secret`,
Presigned Uploads sowie asynchronen Requests. Seedance 2.0 ist im offiziellen
Higgsfield-CLI als `seedance_2_0` verfügbar. Der öffentliche REST-OpenAPI-Katalog
nennt aktuell jedoch keinen festen Seedance-2.0-Endpoint. Deshalb wird dieser
Pfad mit `HIGGSFIELD_SEEDANCE_ENDPOINT` explizit aus Higgsfield Cloud oder vom
Higgsfield-Support übernommen. Der Code verwendet keinen erratenen privaten
Web-Endpoint.

Quellen:

- [Higgsfield API](https://docs.higgsfield.ai/docs)
- [Authentifizierung](https://docs.higgsfield.ai/docs/authentication)
- [Requests und Status](https://docs.higgsfield.ai/docs/concepts/requests)
- [File Uploads](https://docs.higgsfield.ai/docs/concepts/file-uploads)
- [Offizielles Higgsfield-CLI](https://github.com/higgsfield-ai/cli)

## Einrichtung

Serverseitige Zugangsdaten in [Higgsfield Cloud](https://cloud.higgsfield.ai/)
erstellen. Es werden zwei Werte benötigt:

```bash
export HIGGSFIELD_API_KEY_ID='...'
export HIGGSFIELD_API_KEY_SECRET='...'
export HIGGSFIELD_SEEDANCE_ENDPOINT='/endpoint-aus-higgsfield-cloud'
```

Optionale Einstellungen:

```bash
export HIGGSFIELD_OUTPUT_DIR='out/higgsfield'
export HIGGSFIELD_REQUEST_TIMEOUT_SECONDS='30'
export HIGGSFIELD_GENERATION_TIMEOUT_SECONDS='1800'
```

`.env`-Dateien und reale MCP-Konfigurationen werden durch `.gitignore`
ausgeschlossen. Der Adapter sendet den Authorization Header ausschließlich an
`https://api.higgsfield.ai`. Uploads verwenden die von Higgsfield gelieferten
Presigned Headers und erhalten niemals die API-Zugangsdaten.

## CLI

Konfiguration prüfen und Request validieren. Beides verursacht keine Kosten:

```bash
python3 -m higgsfield.cli status
python3 -m higgsfield.cli plan higgsfield/seedance-request.example.json
```

Asynchron absenden oder bis zum geprüften Download warten:

```bash
python3 -m higgsfield.cli submit \
  higgsfield/seedance-request.example.json \
  --acknowledge-paid-generation

python3 -m higgsfield.cli generate \
  higgsfield/seedance-request.example.json \
  --acknowledge-paid-generation
```

Jede bezahlte Erzeugung verlangt die explizite Bestätigung. `generate` pollt
mit Backoff, stoppt bei `completed`, `failed`, `nsfw` oder `canceled` und legt
MP4 sowie Manifest unter `out/higgsfield/` ab. Ein vorhandenes Ergebnis wird
nicht still überschrieben.

## Seedance-Parameter

Unterstützt werden die Parameter des offiziellen CLI-Katalogs:

| Feld | Werte / Grenze |
|---|---|
| `prompt` | Pflicht, maximal 8'000 Zeichen |
| `duration` | 1 bis 15 Sekunden |
| `aspect_ratio` | `auto`, `16:9`, `9:16`, `4:3`, `3:4`, `1:1`, `21:9` |
| `resolution` | `480p`, `720p`, `1080p`, `4k` |
| `mode` | `std`, `fast`; `fast` nur 480p/720p |
| `bitrate_mode` | `standard`, `high` |
| `genre` | `auto`, `action`, `horror`, `comedy`, `noir`, `drama`, `epic` |
| Referenzen | maximal 9 Bilder, 3 Videos, 3 Audios und 12 Dateien total |

Lokale Referenzen werden vor dem Request hochgeladen. Zulässig sind JPEG, PNG,
WebP, GIF, WAV und MP4 entsprechend dem jeweiligen Feld. Öffentliche HTTPS-URLs
werden direkt verwendet. Audio-Referenzen benötigen mindestens eine visuelle
Referenz.

## MCP

`higgsfield/mcp-config.example.json` in den MCP-Client übernehmen. Der gestartete
Prozess erbt die drei oben gesetzten Umgebungsvariablen. Folgende Tools stehen
zur Verfügung:

- `higgsfield_status`
- `higgsfield_seedance_plan`
- `higgsfield_seedance_submit`
- `higgsfield_seedance_generate`
- `higgsfield_request_status`
- `higgsfield_request_cancel`

`status` gibt nur an, ob beide Credential-Werte vorhanden sind. Key ID und
Secret werden nie zurückgegeben. Resultat-URLs von Status und Cancel werden vor
jedem authentifizierten Request auf den offiziellen API-Host geprüft.

## Falls der REST-Endpoint noch nicht freigeschaltet ist

Dann ist das offizielle CLI der unterstützte Übergangsweg:

```bash
brew install higgsfield-ai/tap/higgsfield
higgsfield auth login
higgsfield generate create seedance_2_0 \
  --prompt 'Controlled product-film shot on black' \
  --aspect_ratio 16:9 --duration 5 --resolution 1080p \
  --mode std --bitrate_mode high --wait
```

Das CLI verwendet einen Browser-Login und nicht die serverseitigen API-Secrets.
Es wird daher bewusst nicht heimlich vom REST-Adapter aufgerufen.
