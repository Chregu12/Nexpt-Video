#!/usr/bin/env python3
"""
Erzeugt aus timing.json ein FCPXML fuer Final Cut Pro.

Jede Szene liegt als eigener Clip auf der Spine — so laesst sich in FCP
jede Szene einzeln auf die aufgenommene Off-Stimme schieben, ohne den Rest
zu verschieben. Marker tragen Akt, Szenen-ID und den Sprechertext.

    python3 fcpxml.py            -> out/NEXPT-Keynote.fcpxml
"""
import json, hashlib
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
OUT  = ROOT.parent / "out"
cfg  = json.loads((ROOT / "timing.json").read_text(encoding="utf-8"))
FPS  = cfg["meta"]["fps"]; W = cfg["meta"]["width"]; H = cfg["meta"]["height"]

FD   = f"100/{FPS*100}s"                       # frameDuration, 30p -> 100/3000s
def tc(sec):                                   # Sekunden -> rationale FCP-Zeit auf Frame gerastert
    return f"{int(round(sec*FPS))*100}/{FPS*100}s"
def uid(s): return hashlib.md5(s.encode()).hexdigest().upper()

res, spine, off = [], [], 0.0
res.append(f'<format id="r1" name="FFVideoFormat{H}p{FPS}" frameDuration="{FD}" '
           f'width="{W}" height="{H}" colorSpace="1-1-1 (Rec. 709)"/>')

for i, s in enumerate(cfg["scenes"], 1):
    aid, dur = f"a{i}", tc(s["dur"])
    src = f"scenes/{s['id']}.mov"              # relativ: .fcpxml neben dem Ordner scenes/ lassen
    res.append(
        f'<asset id="{aid}" name="{escape(s["id"])}" uid="{uid(s["id"])}" start="0s" '
        f'duration="{dur}" hasVideo="1" format="r1" videoSources="1">'
        f'<media-rep kind="original-media" sig="{uid(src)}" src="{src}"/></asset>')

    head = escape("Akt " + s["act"] + " \u00b7 " + s["id"])
    mk = [f'<marker start="0s" duration="{FD}" value="{head}"/>']
    if s.get("vo"):
        mk.append(f'<marker start="0s" duration="{FD}" value="{escape("VO: " + s["vo"])}"/>')
    if s.get("bgFlip"):
        mk.append(f'<marker start="{tc(s["bgFlip"]["t"])}" duration="{FD}" '
                  f'value="{escape("BG → " + s["bgFlip"]["to"])}"/>')
    spine.append(
        f'<asset-clip ref="{aid}" offset="{tc(off)}" name="{escape(s["id"])}" '
        f'start="0s" duration="{dur}" format="r1" tcFormat="NDF">'
        + "".join(mk) + '</asset-clip>')
    off += s["dur"]

xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.10">
  <resources>
    {chr(10).join("    " + r for r in res).strip()}
  </resources>
  <library name="NEXPT Video">
    <event name="NEXPT Keynote">
      <project name="{escape(cfg["meta"]["title"])}">
        <sequence format="r1" duration="{tc(off)}" tcStart="0s" tcFormat="NDF"
                  audioLayout="stereo" audioRate="48k">
          <spine>
            {chr(10).join("            " + c for c in spine).strip()}
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
'''
OUT.mkdir(exist_ok=True)
dst = OUT / "NEXPT-Keynote.fcpxml"
dst.write_text(xml, encoding="utf-8")

import xml.etree.ElementTree as ET
ET.fromstring(xml.split("\n",2)[2])            # DOCTYPE ueberspringen, Rest muss parsen
print(f"{dst}  ·  {len(cfg['scenes'])} Clips  ·  {off:.1f}s  ·  XML valide")
