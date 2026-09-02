"""Safe, dependency-free Higgsfield API adapter for Seedance 2.0.

The public Higgsfield API uses server-side key-id/secret authentication and an
asynchronous request lifecycle.  Seedance 2.0 is available in Higgsfield's
official CLI, but its REST model endpoint is not currently published in the
public OpenAPI document.  The endpoint is therefore explicit configuration,
never a guessed private URL.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import mimetypes
import os
import random
import re
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

API_BASE_URL = "https://api.higgsfield.ai"
TERMINAL_STATUSES = {"completed", "failed", "nsfw", "canceled"}
ASPECT_RATIOS = {"auto", "16:9", "9:16", "4:3", "3:4", "1:1", "21:9"}
RESOLUTIONS = {"480p", "720p", "1080p", "4k"}
MODES = {"std", "fast"}
BITRATE_MODES = {"standard", "high"}
GENRES = {"auto", "action", "horror", "comedy", "noir", "drama", "epic"}
REQUEST_KEYS = {
    "prompt",
    "aspect_ratio",
    "duration",
    "resolution",
    "mode",
    "bitrate_mode",
    "genre",
    "generate_audio",
    "start_image",
    "end_image",
    "image_references",
    "video_references",
    "audio_references",
}
REFERENCE_KEYS = (
    "start_image",
    "end_image",
    "image_references",
    "video_references",
    "audio_references",
)
CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".wav": "audio/wav",
    ".mp4": "video/mp4",
}
REFERENCE_SUFFIXES = {
    "start_image": {".jpg", ".jpeg", ".png", ".webp", ".gif"},
    "end_image": {".jpg", ".jpeg", ".png", ".webp", ".gif"},
    "image_references": {".jpg", ".jpeg", ".png", ".webp", ".gif"},
    "video_references": {".mp4"},
    "audio_references": {".wav"},
}


class HiggsfieldError(RuntimeError):
    """A safe error from configuration, transport, or generation."""


class Transport(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None,
        timeout: float,
    ) -> dict[str, Any]: ...

    def upload_file(
        self,
        url: str,
        path: Path,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> None: ...

    def download_file(
        self,
        url: str,
        path: Path,
        *,
        timeout: float,
        max_bytes: int,
    ) -> dict[str, Any]: ...


def _positive_number(name: str, raw: str, *, minimum: float, maximum: float) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise HiggsfieldError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise HiggsfieldError(f"{name} must be between {minimum:g} and {maximum:g}")
    return value


def _validate_api_base_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.rstrip("/"))
    if parsed.scheme != "https" or parsed.hostname != "api.higgsfield.ai":
        raise HiggsfieldError(
            "HIGGSFIELD_API_BASE_URL must be https://api.higgsfield.ai; "
            "credentials are never sent to another host"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HiggsfieldError(
            "HIGGSFIELD_API_BASE_URL must not contain credentials or a query"
        )
    return value.rstrip("/")


def _validate_endpoint(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    endpoint = value.strip()
    parsed = urllib.parse.urlsplit(endpoint)
    if (
        not endpoint.startswith("/")
        or endpoint.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or ".." in parsed.path.split("/")
    ):
        raise HiggsfieldError(
            "HIGGSFIELD_SEEDANCE_ENDPOINT must be a relative API path such as /provider/model/action"
        )
    return endpoint


@dataclass(frozen=True)
class HiggsfieldSettings:
    api_key_id: str | None = None
    api_key_secret: str | None = field(default=None, repr=False)
    seedance_endpoint: str | None = None
    base_url: str = API_BASE_URL
    output_dir: Path = Path("out/higgsfield")
    request_timeout_seconds: float = 30.0
    generation_timeout_seconds: float = 1800.0
    max_download_bytes: int = 2_000_000_000

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        require_credentials: bool = False,
        require_endpoint: bool = False,
    ) -> HiggsfieldSettings:
        env = os.environ if environ is None else environ
        key_id = env.get("HIGGSFIELD_API_KEY_ID", "").strip() or None
        secret = env.get("HIGGSFIELD_API_KEY_SECRET", "").strip() or None
        if bool(key_id) != bool(secret):
            raise HiggsfieldError(
                "HIGGSFIELD_API_KEY_ID and HIGGSFIELD_API_KEY_SECRET must be set together"
            )
        if require_credentials and not (key_id and secret):
            raise HiggsfieldError(
                "missing HIGGSFIELD_API_KEY_ID and HIGGSFIELD_API_KEY_SECRET"
            )
        endpoint = _validate_endpoint(env.get("HIGGSFIELD_SEEDANCE_ENDPOINT"))
        if require_endpoint and not endpoint:
            raise HiggsfieldError(
                "missing HIGGSFIELD_SEEDANCE_ENDPOINT; use the Seedance 2.0 endpoint "
                "assigned in Higgsfield Cloud or by Higgsfield support"
            )
        request_timeout = _positive_number(
            "HIGGSFIELD_REQUEST_TIMEOUT_SECONDS",
            env.get("HIGGSFIELD_REQUEST_TIMEOUT_SECONDS", "30"),
            minimum=1,
            maximum=300,
        )
        generation_timeout = _positive_number(
            "HIGGSFIELD_GENERATION_TIMEOUT_SECONDS",
            env.get("HIGGSFIELD_GENERATION_TIMEOUT_SECONDS", "1800"),
            minimum=30,
            maximum=21600,
        )
        return cls(
            api_key_id=key_id,
            api_key_secret=secret,
            seedance_endpoint=endpoint,
            base_url=_validate_api_base_url(
                env.get("HIGGSFIELD_API_BASE_URL", API_BASE_URL)
            ),
            output_dir=Path(env.get("HIGGSFIELD_OUTPUT_DIR", "out/higgsfield")),
            request_timeout_seconds=request_timeout,
            generation_timeout_seconds=generation_timeout,
        )

    @property
    def ready(self) -> bool:
        return bool(self.api_key_id and self.api_key_secret and self.seedance_endpoint)


def _error_detail(body: bytes) -> str:
    text = body[:65536].decode("utf-8", errors="replace").strip()
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text[:500] or "empty response"
    if isinstance(value, dict):
        detail = value.get("detail") or value.get("error") or value.get("message")
        if detail:
            return str(detail)[:500]
    return str(value)[:500]


class HttpTransport:
    """Production HTTP transport. API credentials are caller-controlled headers."""

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None,
        timeout: float,
    ) -> dict[str, Any]:
        data = None
        request_headers = dict(headers)
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url, data=data, headers=request_headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read(10_000_001)
                if len(body) > 10_000_000:
                    raise HiggsfieldError("Higgsfield JSON response exceeds 10 MB")
        except urllib.error.HTTPError as exc:
            detail = _error_detail(exc.read())
            raise HiggsfieldError(
                f"Higgsfield API returned HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HiggsfieldError(f"Higgsfield API request failed: {exc}") from exc
        if not body:
            return {}
        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HiggsfieldError("Higgsfield API returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise HiggsfieldError("Higgsfield API response must be a JSON object")
        return result

    def upload_file(
        self,
        url: str,
        path: Path,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise HiggsfieldError("presigned upload URL must use HTTPS")
        connection = http.client.HTTPSConnection(
            parsed.hostname,
            parsed.port or 443,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        upload_headers = {str(key): str(value) for key, value in headers.items()}
        upload_headers["Content-Length"] = str(path.stat().st_size)
        try:
            connection.putrequest("PUT", target)
            for key, value in upload_headers.items():
                connection.putheader(key, value)
            connection.endheaders()
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    connection.send(chunk)
            response = connection.getresponse()
            body = response.read(65536)
            if not 200 <= response.status < 300:
                raise HiggsfieldError(
                    f"presigned upload returned HTTP {response.status}: {_error_detail(body)}"
                )
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise HiggsfieldError(f"media upload failed: {exc}") from exc
        finally:
            connection.close()

    def download_file(
        self,
        url: str,
        path: Path,
        *,
        timeout: float,
        max_bytes: int,
    ) -> dict[str, Any]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise HiggsfieldError("output URL must use HTTPS")
        request = urllib.request.Request(url, headers={"User-Agent": "NEXPT-Video/1.0"})
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        temporary: Path | None = None
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                final_url = urllib.parse.urlsplit(response.geturl())
                if final_url.scheme != "https":
                    raise HiggsfieldError("output redirect must remain on HTTPS")
                content_type = response.headers.get_content_type()
                if content_type not in {"video/mp4", "application/octet-stream"}:
                    raise HiggsfieldError(
                        f"unexpected Higgsfield output content type: {content_type}"
                    )
                with tempfile.NamedTemporaryFile(
                    prefix=f".{path.name}.", dir=path.parent, delete=False
                ) as target:
                    temporary = Path(target.name)
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > max_bytes:
                            raise HiggsfieldError(
                                "Higgsfield output exceeds download limit"
                            )
                        digest.update(chunk)
                        target.write(chunk)
            if path.exists():
                raise HiggsfieldError(f"refusing to overwrite existing output: {path}")
            os.replace(temporary, path)
            temporary = None
        except urllib.error.HTTPError as exc:
            raise HiggsfieldError(
                f"Higgsfield output download returned HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HiggsfieldError(f"Higgsfield output download failed: {exc}") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return {
            "path": str(path.resolve()),
            "bytes": size,
            "sha256": digest.hexdigest(),
        }


def _is_public_https_url(value: str) -> bool:
    parsed = urllib.parse.urlsplit(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def _validate_reference(value: Any, *, key: str) -> str:
    if type(value) is not str or not value.strip():
        raise HiggsfieldError(f"{key} references must be non-empty strings")
    reference = value.strip()
    if _is_public_https_url(reference):
        return reference
    path = Path(reference).expanduser()
    if not path.is_file():
        raise HiggsfieldError(f"{key} reference does not exist: {reference}")
    suffix = path.suffix.lower()
    if suffix not in REFERENCE_SUFFIXES[key]:
        allowed = ", ".join(sorted(REFERENCE_SUFFIXES[key]))
        raise HiggsfieldError(f"{key} supports only {allowed}: {reference}")
    return str(path.resolve())


def _enum(request: Mapping[str, Any], key: str, default: str, values: set[str]) -> str:
    value = request.get(key, default)
    if type(value) is not str or value not in values:
        raise HiggsfieldError(f"{key} must be one of: {', '.join(sorted(values))}")
    return value


def normalize_seedance_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise HiggsfieldError("Seedance request must be a JSON object")
    unknown = sorted(set(request) - REQUEST_KEYS)
    if unknown:
        raise HiggsfieldError(f"unsupported Seedance fields: {', '.join(unknown)}")
    prompt = request.get("prompt")
    if type(prompt) is not str or not prompt.strip():
        raise HiggsfieldError("prompt is required")
    prompt = prompt.strip()
    if len(prompt) > 8000:
        raise HiggsfieldError("prompt must not exceed 8000 characters")
    duration = request.get("duration", 5)
    if type(duration) is not int or not 1 <= duration <= 15:
        raise HiggsfieldError("duration must be an integer between 1 and 15 seconds")
    generate_audio = request.get("generate_audio", True)
    if type(generate_audio) is not bool:
        raise HiggsfieldError("generate_audio must be a boolean")
    normalized: dict[str, Any] = {
        "prompt": prompt,
        "aspect_ratio": _enum(request, "aspect_ratio", "16:9", ASPECT_RATIOS),
        "duration": duration,
        "resolution": _enum(request, "resolution", "720p", RESOLUTIONS),
        "mode": _enum(request, "mode", "std", MODES),
        "bitrate_mode": _enum(request, "bitrate_mode", "standard", BITRATE_MODES),
        "genre": _enum(request, "genre", "auto", GENRES),
        "generate_audio": generate_audio,
    }
    for key in ("start_image", "end_image"):
        if request.get(key) is not None:
            normalized[key] = _validate_reference(request[key], key=key)
    for key in ("image_references", "video_references", "audio_references"):
        values = request.get(key, [])
        if type(values) is not list:
            raise HiggsfieldError(f"{key} must be an array")
        normalized[key] = [_validate_reference(value, key=key) for value in values]
    if (
        len(normalized["image_references"])
        + int("start_image" in normalized)
        + int("end_image" in normalized)
        > 9
    ):
        raise HiggsfieldError("at most 9 image references are allowed")
    if len(normalized["video_references"]) > 3:
        raise HiggsfieldError("at most 3 video references are allowed")
    if len(normalized["audio_references"]) > 3:
        raise HiggsfieldError("at most 3 audio references are allowed")
    total = (
        sum(
            len(normalized[key])
            for key in ("image_references", "video_references", "audio_references")
        )
        + int("start_image" in normalized)
        + int("end_image" in normalized)
    )
    if total > 12:
        raise HiggsfieldError("at most 12 reference files are allowed in total")
    visual_count = (
        len(normalized["image_references"])
        + len(normalized["video_references"])
        + int("start_image" in normalized)
        + int("end_image" in normalized)
    )
    if normalized["audio_references"] and not visual_count:
        raise HiggsfieldError("audio references require at least one visual reference")
    if normalized["mode"] == "fast" and normalized["resolution"] not in {
        "480p",
        "720p",
    }:
        raise HiggsfieldError("fast mode supports only 480p or 720p")
    return normalized


class HiggsfieldClient:
    def __init__(
        self,
        settings: HiggsfieldSettings,
        *,
        transport: Transport | None = None,
    ) -> None:
        if not settings.api_key_id or not settings.api_key_secret:
            raise HiggsfieldError("Higgsfield API credentials are not configured")
        self.settings = settings
        self.transport: Transport = transport or HttpTransport()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": (
                f"Key {self.settings.api_key_id}:{self.settings.api_key_secret}"
            ),
            "Accept": "application/json",
            "User-Agent": "NEXPT-Video/1.0",
        }

    def _trusted_api_url(self, value: str) -> str:
        if value.startswith("/") and not value.startswith("//"):
            value = f"{self.settings.base_url}{value}"
        expected = urllib.parse.urlsplit(self.settings.base_url)
        parsed = urllib.parse.urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname != expected.hostname
            or parsed.port not in {None, 443}
            or parsed.username
            or parsed.password
        ):
            raise HiggsfieldError(
                "refusing to send credentials outside api.higgsfield.ai"
            )
        return value

    def _request(
        self,
        method: str,
        url: str,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.transport.request_json(
            method,
            self._trusted_api_url(url),
            headers=self._headers,
            payload=payload,
            timeout=self.settings.request_timeout_seconds,
        )

    def upload(self, path_value: str) -> str:
        path = Path(path_value)
        suffix = path.suffix.lower()
        content_type = CONTENT_TYPES.get(suffix) or mimetypes.guess_type(path.name)[0]
        if content_type not in set(CONTENT_TYPES.values()):
            raise HiggsfieldError(f"unsupported upload type: {path}")
        upload = self._request(
            "POST",
            "/files/generate-upload-url",
            {"content_type": content_type},
        )
        public_url = upload.get("public_url")
        upload_url = upload.get("upload_url")
        upload_headers = upload.get("upload_headers", {})
        if not isinstance(public_url, str) or not _is_public_https_url(public_url):
            raise HiggsfieldError("Higgsfield returned an invalid public_url")
        if not isinstance(upload_url, str) or not _is_public_https_url(upload_url):
            raise HiggsfieldError("Higgsfield returned an invalid upload_url")
        if not isinstance(upload_headers, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in upload_headers.items()
        ):
            raise HiggsfieldError("Higgsfield returned invalid upload_headers")
        # API credentials are deliberately not included in this storage request.
        self.transport.upload_file(
            upload_url,
            path,
            headers=upload_headers,
            timeout=self.settings.request_timeout_seconds,
        )
        return public_url

    def prepare_payload(self, request: Mapping[str, Any]) -> dict[str, Any]:
        normalized = normalize_seedance_request(request)
        payload = dict(normalized)
        for key in REFERENCE_KEYS:
            if key not in payload:
                continue
            values = payload[key] if isinstance(payload[key], list) else [payload[key]]
            prepared = [
                value if _is_public_https_url(value) else self.upload(value)
                for value in values
            ]
            payload[key] = prepared if isinstance(payload[key], list) else prepared[0]
        return payload

    def submit(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        endpoint = _validate_endpoint(self.settings.seedance_endpoint)
        if not endpoint:
            raise HiggsfieldError("HIGGSFIELD_SEEDANCE_ENDPOINT is not configured")
        result = self._request("POST", endpoint, payload)
        request_id = result.get("request_id")
        status_url = result.get("status_url")
        cancel_url = result.get("cancel_url")
        if not isinstance(request_id, str) or not request_id:
            raise HiggsfieldError("Higgsfield submission did not return request_id")
        if not isinstance(status_url, str):
            raise HiggsfieldError("Higgsfield submission did not return status_url")
        self._trusted_api_url(status_url)
        if cancel_url is not None:
            if not isinstance(cancel_url, str):
                raise HiggsfieldError(
                    "Higgsfield submission returned invalid cancel_url"
                )
            self._trusted_api_url(cancel_url)
        return result

    def get_status(self, status_url: str) -> dict[str, Any]:
        result = self._request("GET", status_url)
        status_value = result.get("status")
        if status_value not in TERMINAL_STATUSES | {"queued", "in_progress"}:
            raise HiggsfieldError(
                f"unknown Higgsfield request status: {status_value!r}"
            )
        return result

    def cancel(self, cancel_url: str) -> dict[str, Any]:
        self._request("POST", cancel_url)
        return {"status": "cancel_requested", "cancel_url": cancel_url}

    def wait(
        self,
        initial: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> dict[str, Any]:
        result = dict(initial)
        status_value = result.get("status")
        status_url = result.get("status_url")
        if status_value in TERMINAL_STATUSES:
            return result
        if not isinstance(status_url, str):
            raise HiggsfieldError("request has no status_url")
        timeout = timeout_seconds or self.settings.generation_timeout_seconds
        if not 1 <= timeout <= 21600:
            raise HiggsfieldError("wait timeout must be between 1 and 21600 seconds")
        deadline = monotonic() + timeout
        delay = 2.0
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise HiggsfieldError("Higgsfield generation timed out")
            sleep(min(delay + jitter(0, 0.5), remaining))
            result = self.get_status(status_url)
            if result.get("status") in TERMINAL_STATUSES:
                return result
            delay = min(delay * 1.5, 10.0)

    def download_completed(self, result: Mapping[str, Any]) -> dict[str, Any]:
        if result.get("status") != "completed":
            raise HiggsfieldError(
                f"cannot download request with status {result.get('status')!r}"
            )
        video = result.get("video")
        url = video.get("url") if isinstance(video, Mapping) else None
        if not isinstance(url, str) or not _is_public_https_url(url):
            raise HiggsfieldError("completed request contains no valid video URL")
        request_id = str(result.get("request_id", "seedance"))
        safe_id = re.sub(r"[^A-Za-z0-9._-]", "-", request_id)[:120] or "seedance"
        output_path = self.settings.output_dir / f"seedance-{safe_id}.mp4"
        output = self.transport.download_file(
            url,
            output_path,
            timeout=self.settings.request_timeout_seconds,
            max_bytes=self.settings.max_download_bytes,
        )
        output["source_url"] = url
        return output


def status(
    settings: HiggsfieldSettings | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    current = settings or HiggsfieldSettings.from_env(environ)
    return {
        "service": "Higgsfield Seedance 2.0",
        "api_base_url": current.base_url,
        "credentials_configured": bool(current.api_key_id and current.api_key_secret),
        "endpoint_configured": bool(current.seedance_endpoint),
        "ready": current.ready,
        "output_dir": str(current.output_dir),
        "credential_values_exposed": False,
        "model": "seedance_2_0",
        "note": (
            "The Seedance 2.0 REST endpoint is account configuration because it "
            "is not currently named in Higgsfield's public OpenAPI schema."
        ),
    }


def build_plan(
    request: Mapping[str, Any],
    *,
    settings: HiggsfieldSettings | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    current = settings or HiggsfieldSettings.from_env(environ)
    normalized = normalize_seedance_request(request)
    uploads = []
    for key in REFERENCE_KEYS:
        if key not in normalized:
            continue
        values = (
            normalized[key] if isinstance(normalized[key], list) else [normalized[key]]
        )
        uploads.extend(
            {"field": key, "path": value}
            for value in values
            if not _is_public_https_url(value)
        )
    return {
        "provider": "higgsfield",
        "model": "seedance_2_0",
        "endpoint": current.seedance_endpoint,
        "endpoint_configured": bool(current.seedance_endpoint),
        "request": normalized,
        "uploads": uploads,
        "paid_operation": True,
        "executes": False,
        "credentials_exposed": False,
    }


def build_handoff(output: Mapping[str, Any]) -> dict[str, Any]:
    path_value = output.get("path")
    if not isinstance(path_value, str):
        raise HiggsfieldError("downloaded output path is missing")
    path = Path(path_value).resolve()
    return {
        "video_path": str(path),
        "final_cut": {
            "operation": "import_media",
            "path": str(path),
            "note": "Import the verified MP4 as a source clip; retain the manifest beside it.",
        },
        "motion": {
            "operation": "import_media_layer",
            "path": str(path),
            "note": "Use the clip as footage inside a reviewed Motion template; do not rewrite .motn internals.",
        },
        "audio": {
            "generated_with_video": True,
            "note": "Keep generated clip audio separate from the GarageBand music and SFX masters.",
        },
    }


def generate_seedance(
    request: Mapping[str, Any],
    *,
    acknowledge_paid_generation: bool,
    wait: bool = True,
    settings: HiggsfieldSettings | None = None,
    environ: Mapping[str, str] | None = None,
    transport: Transport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    jitter: Callable[[float, float], float] = random.uniform,
) -> dict[str, Any]:
    if acknowledge_paid_generation is not True:
        raise HiggsfieldError("acknowledge_paid_generation=true is required")
    current = settings or HiggsfieldSettings.from_env(
        environ, require_credentials=True, require_endpoint=True
    )
    client = HiggsfieldClient(current, transport=transport)
    payload = client.prepare_payload(request)
    submitted = client.submit(payload)
    if not wait:
        return {
            "submitted": submitted,
            "request": payload,
            "download": None,
            "handoff": None,
        }
    completed = client.wait(submitted, sleep=sleep, monotonic=monotonic, jitter=jitter)
    status_value = completed.get("status")
    if status_value != "completed":
        detail = completed.get("error") or completed.get("detail") or status_value
        raise HiggsfieldError(
            f"Higgsfield generation ended with {status_value}: {detail}"
        )
    download = client.download_completed(completed)
    manifest = {
        "provider": "higgsfield",
        "model": "seedance_2_0",
        "request": payload,
        "result": completed,
        "download": download,
    }
    manifest_path = Path(download["path"]).with_suffix(".json")
    if manifest_path.exists():
        raise HiggsfieldError(
            f"refusing to overwrite existing manifest: {manifest_path}"
        )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "submitted": submitted,
        "completed": completed,
        "download": download,
        "manifest_path": str(manifest_path.resolve()),
        "handoff": build_handoff(download),
    }
