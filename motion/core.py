"""Dependency-free Apple Motion control through macOS Accessibility.

Motion has no documented general project-automation API.  These helpers use
only explicit project files, keyboard shortcuts and discoverable AX elements.
They fail closed outside macOS or when Accessibility permission is missing.
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
import time
from pathlib import Path
from typing import Any


APP_NAME = "Motion"
APP_PATH = Path("/Applications/Motion.app")
PROJECT_EXTENSIONS = {".motn", ".moti", ".motr", ".moef"}


class MotionError(RuntimeError):
    pass


def _require_macos() -> None:
    if platform.system() != "Darwin":
        raise MotionError("Apple Motion automation requires macOS")


def _run(command: list[str], *, timeout: float = 30) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MotionError(str(exc)) from exc
    if result.returncode:
        message = (result.stderr or result.stdout).strip()
        if "not allowed assistive access" in message.lower() or "-1719" in message:
            message += "; allow your terminal/agent in System Settings > Privacy & Security > Accessibility"
        raise MotionError(message or f"command failed with status {result.returncode}")
    return result.stdout.strip()


def _osa(script: str, *arguments: str, timeout: float = 30) -> str:
    _require_macos()
    command = ["osascript", "-l", "AppleScript", "-e", script, "--", *map(str, arguments)]
    return _run(command, timeout=timeout)


def app_installed() -> bool:
    return platform.system() == "Darwin" and APP_PATH.is_dir()


def is_running() -> bool:
    if platform.system() != "Darwin":
        return False
    result = subprocess.run(["pgrep", "-x", APP_NAME], capture_output=True, check=False)
    return result.returncode == 0


def app_version() -> str | None:
    if not app_installed():
        return None
    return _run(["defaults", "read", str(APP_PATH / "Contents/Info"), "CFBundleShortVersionString"])


def status() -> dict[str, Any]:
    return {
        "platform": platform.system(),
        "supported": platform.system() == "Darwin",
        "installed": app_installed(),
        "running": is_running(),
        "version": app_version(),
        "app_path": str(APP_PATH),
    }


def capabilities(*, include_live: bool = True) -> dict[str, Any]:
    result = {
        "application": APP_NAME,
        "transport": "MCP over stdio",
        "project_strategy": "real Motion template + explicit placeholders",
        "supported": [
            "validate declarative animation specs", "inspect Motion project files",
            "render safe template copies", "launch/open/save Motion projects",
            "discover and activate menus", "inspect/click/set Accessibility UI elements",
            "keyboard shortcuts", "screenshots", "compile and run guarded plans",
        ],
        "limitations": [
            "Apple does not document a general Motion project-automation API",
            "arbitrary .motn XML is never invented by this bridge",
            "live control requires Motion plus macOS Accessibility permission",
            "export presets and dialogs vary with the installed Motion version and language",
        ],
    }
    if include_live:
        result["live"] = status()
    return result


def launch(*, wait_seconds: float = 1.5) -> dict[str, Any]:
    _require_macos()
    if not app_installed():
        raise MotionError(f"Motion is not installed at {APP_PATH}")
    _run(["open", "-a", APP_NAME])
    time.sleep(max(0, wait_seconds))
    return status()


def activate() -> None:
    _osa('tell application "Motion" to activate')


def open_project(path: str | Path, *, wait_seconds: float = 1.5) -> dict[str, Any]:
    project = Path(path).expanduser().resolve()
    if not project.is_file():
        raise MotionError(f"project does not exist: {project}")
    if project.suffix.lower() not in PROJECT_EXTENSIONS:
        raise MotionError(f"unsupported Motion file extension: {project.suffix}")
    _require_macos()
    _run(["open", "-a", APP_NAME, str(project)])
    time.sleep(max(0, wait_seconds))
    return {"opened": str(project), "running": is_running()}


def shortcut(keys: str | list[str]) -> dict[str, Any]:
    if isinstance(keys, str):
        parts = [part.strip().lower() for part in keys.split("+") if part.strip()]
    else:
        parts = [str(part).strip().lower() for part in keys]
    if not parts:
        raise MotionError("shortcut must contain at least one key")
    modifiers = {"cmd": "command down", "command": "command down", "shift": "shift down",
                 "alt": "option down", "option": "option down", "ctrl": "control down",
                 "control": "control down"}
    held = [modifiers[part] for part in parts[:-1] if part in modifiers]
    if len(held) != len(parts) - 1:
        raise MotionError("only the final shortcut component may be a regular key")
    key = parts[-1]
    if len(key) != 1 or not key.isprintable():
        raise MotionError("final shortcut key must be one printable character")
    suffix = f" using {{{', '.join(held)}}}" if held else ""
    _osa(f'tell application "Motion" to activate\ndelay 0.2\ntell application "System Events" to keystroke {json.dumps(key)}{suffix}')
    return {"shortcut": "+".join(parts)}


def type_text(text: str) -> dict[str, Any]:
    if not isinstance(text, str) or len(text) > 10000:
        raise MotionError("text must be a string of at most 10,000 characters")
    _osa('on run argv\ntell application "Motion" to activate\ndelay 0.2\ntell application "System Events" to keystroke (item 1 of argv)\nend run', text)
    return {"typed_characters": len(text)}


def save() -> dict[str, Any]:
    return shortcut("cmd+s")


def export_dialog() -> dict[str, Any]:
    """Open Motion's Export Movie dialog (Command-E); does not confirm export."""
    return shortcut("cmd+e")


def menu_map() -> list[dict[str, Any]]:
    script = r'''
tell application "Motion" to activate
delay 0.3
tell application "System Events"
  tell process "Motion"
    set rows to {}
    repeat with topItem in menu bar items of menu bar 1
      set topName to name of topItem
      try
        repeat with childItem in menu items of menu 1 of topItem
          set end of rows to topName & tab & (name of childItem) & tab & (enabled of childItem as text)
        end repeat
      end try
    end repeat
    set AppleScript's text item delimiters to linefeed
    return rows as text
  end tell
end tell
'''
    raw = _osa(script)
    items = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            items.append({"menu": parts[0], "item": parts[1], "enabled": parts[2] == "true"})
    return items


def find_menu_items(query: str) -> list[dict[str, Any]]:
    needle = query.casefold()
    return [item for item in menu_map() if needle in item["menu"].casefold() or needle in item["item"].casefold()]


def click_menu(menu: str, item: str) -> dict[str, Any]:
    script = '''on run argv
tell application "Motion" to activate
delay 0.2
tell application "System Events" to tell process "Motion"
  click menu item (item 2 of argv) of menu 1 of menu bar item (item 1 of argv) of menu bar 1
end tell
end run'''
    _osa(script, menu, item)
    return {"clicked": {"menu": menu, "item": item}}


def ui_snapshot(*, max_depth: int = 3, max_items: int = 400) -> dict[str, Any]:
    if not 0 <= max_depth <= 8 or not 1 <= max_items <= 2000:
        raise MotionError("max_depth must be 0..8 and max_items 1..2000")
    script = r'''on run argv
set maxDepth to (item 1 of argv) as integer
set maxItems to (item 2 of argv) as integer
tell application "Motion" to activate
delay 0.3
tell application "System Events"
 tell process "Motion"
  if (count of windows) is 0 then return "[]"
  set rows to my walk(window 1, "window[1]", 0, maxDepth, maxItems, {})
  set AppleScript's text item delimiters to linefeed
  return rows as text
 end tell
end tell
end run
on walk(el, p, d, maxDepth, maxItems, rows)
 if (count rows) >= maxItems then return rows
 set r to ""; set n to ""; set v to ""
 try
  set r to role of el
 end try
 try
  set n to name of el
 end try
 try
  set v to value of el as text
 end try
 set end of rows to p & tab & r & tab & n & tab & v
 if d < maxDepth then
  try
   set cs to UI elements of el
   repeat with i from 1 to count cs
    set rows to my walk(item i of cs, p & "/ui[" & i & "]", d + 1, maxDepth, maxItems, rows)
    if (count rows) >= maxItems then exit repeat
   end repeat
  end try
 end if
 return rows
end walk'''
    raw = _osa(script, str(max_depth), str(max_items))
    elements = []
    for line in raw.splitlines():
        path, role, name, value = (line.split("\t", 3) + ["", "", "", ""])[:4]
        elements.append({"path": path, "role": role, "name": name, "value": value})
    return {"elements": elements, "truncated": len(elements) >= max_items}


def find_ui_elements(query: str, *, max_depth: int = 5, max_items: int = 800) -> list[dict[str, Any]]:
    needle = query.casefold()
    return [row for row in ui_snapshot(max_depth=max_depth, max_items=max_items)["elements"]
            if needle in row["name"].casefold() or needle in row["value"].casefold() or needle in row["role"].casefold()]


def _validate_ui_path(path: str) -> list[int]:
    if not isinstance(path, str) or not path.startswith("window[1]"):
        raise MotionError("UI path must start with window[1]")
    suffix = path[len("window[1]"):]
    tokens = re.findall(r"/ui\[(\d+)\]", suffix)
    if "".join(f"/ui[{token}]" for token in tokens) != suffix:
        raise MotionError("invalid UI path")
    indexes = [int(token) for token in tokens]
    if any(index < 1 for index in indexes):
        raise MotionError("UI indices are one-based")
    return indexes


def _ui_path_script(action: str, path: str) -> str:
    indexes = _validate_ui_path(path)
    chain = "window 1"
    for index in indexes:
        chain = f"UI element {index} of {chain}"
    if action == "click":
        body = f"click {chain}"
    elif action == "set":
        body = f"set value of {chain} to item 2 of argv"
    elif action == "info":
        body = f'''set el to {chain}
set r to ""; set n to ""; set v to ""
try
 set r to role of el
end try
try
 set n to name of el
end try
try
 set v to value of el as text
end try
return r & tab & n & tab & v'''
    else:
        raise MotionError(f"unsupported UI action: {action}")
    return f'''on run argv
tell application "Motion" to activate
delay 0.2
tell application "System Events" to tell process "Motion"
  {body}
end tell
end run'''


def ui_info_path(path: str) -> dict[str, Any]:
    raw = _osa(_ui_path_script("info", path), path)
    role, name, value = (raw.split("\t", 2) + ["", "", ""])[:3]
    return {"path": path, "role": role, "name": name, "value": value}


def click_ui_path(path: str) -> dict[str, Any]:
    _osa(_ui_path_script("click", path), path)
    return {"clicked": path}


def set_ui_value(path: str, value: Any) -> dict[str, Any]:
    _osa(_ui_path_script("set", path), path, str(value))
    return {"set": path, "value": value}


def screenshot(output_path: str | Path) -> dict[str, Any]:
    output = Path(output_path).expanduser().resolve()
    if output.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise MotionError("screenshot output must be PNG or JPEG")
    _require_macos()
    output.parent.mkdir(parents=True, exist_ok=True)
    activate()
    _run(["screencapture", "-x", str(output)])
    return {"path": str(output), "size": output.stat().st_size}


def run_plan(plan: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("version") != 1 or not isinstance(plan.get("steps"), list):
        raise MotionError("plan must contain version 1 and a steps array")
    handlers = {
        "launch": lambda step: launch(wait_seconds=step.get("wait_seconds", 1.5)),
        "open": lambda step: open_project(step["path"], wait_seconds=step.get("wait_seconds", 1.5)),
        "shortcut": lambda step: shortcut(step["keys"]),
        "type_text": lambda step: type_text(step["text"]),
        "click_menu": lambda step: click_menu(step["menu"], step["item"]),
        "click_ui": lambda step: click_ui_path(step["path"]),
        "set_ui": lambda step: set_ui_value(step["path"], step["value"]),
        "save": lambda step: save(),
        "export_dialog": lambda step: export_dialog(),
        "screenshot": lambda step: screenshot(step["path"]),
        "wait": lambda step: (time.sleep(float(step.get("seconds", 0.5))) or {"waited": float(step.get("seconds", 0.5))}),
    }
    results = []
    for index, step in enumerate(plan["steps"]):
        if not isinstance(step, dict) or step.get("action") not in handlers:
            raise MotionError(f"unsupported plan step {index}: {step!r}")
        if dry_run:
            results.append({"index": index, "action": step["action"], "dry_run": True})
        else:
            results.append({"index": index, "action": step["action"], "result": handlers[step["action"]](step)})
    return {"ok": True, "dry_run": dry_run, "steps": results}
