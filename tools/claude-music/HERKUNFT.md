# Herkunft und Update

Diese Verzeichniskopie stammt unverändert aus:

- Repository: <https://github.com/AgriciDaniel/claude-music>
- Commit: `5aa0173a6b329e059568bef4253e2a62efe8b412`
- Lizenz: MIT, siehe `LICENSE`
- Übernommen: 2. September 2026

`HERKUNFT.md` ist die einzige NEXPT-spezifische Datei in dieser Kopie. Die
Integration liegt außerhalb des Upstreams unter `garageband/generative.py` und
`garageband/mcp.py`. Dadurch kann die Kopie gegen einen neuen Upstream-Commit
ersetzt und separat getestet werden.

ACE-Step und seine Modelle sind nicht enthalten. Der Upstream-Installer lädt
sie separat. Installer und Modellcode müssen vor einem Update erneut geprüft
werden; lokale Konfigurationsdateien und Modellgewichte gehören nicht ins
Repository.
