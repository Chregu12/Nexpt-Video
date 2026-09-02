from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from higgsfield.api import (
    API_BASE_URL,
    HiggsfieldClient,
    HiggsfieldError,
    HiggsfieldSettings,
    build_plan,
    generate_seedance,
    normalize_seedance_request,
    status,
)


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.uploads: list[dict] = []
        self.downloads: list[dict] = []
        self.status_calls = 0

    def request_json(self, method, url, *, headers, payload, timeout):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "payload": payload,
                "timeout": timeout,
            }
        )
        if url.endswith("/files/generate-upload-url"):
            return {
                "public_url": "https://cdn.example.test/input/reference.png",
                "upload_url": "https://storage.example.test/presigned",
                "upload_headers": {
                    "Content-Type": "image/png",
                    "x-amz-tagging": "retention=temporary",
                },
            }
        if url.endswith("/account/seedance-2"):
            return {
                "status": "queued",
                "request_id": "request-123",
                "status_url": f"{API_BASE_URL}/requests/request-123/status",
                "cancel_url": f"{API_BASE_URL}/requests/request-123/cancel",
            }
        if url.endswith("/requests/request-123/status"):
            self.status_calls += 1
            if self.status_calls == 1:
                return {"status": "in_progress", "request_id": "request-123"}
            return {
                "status": "completed",
                "request_id": "request-123",
                "video": {"url": "https://cdn.example.test/output/video.mp4"},
            }
        if url.endswith("/requests/request-123/cancel"):
            return {}
        raise AssertionError(f"unexpected request: {method} {url}")

    def upload_file(self, url, path, *, headers, timeout):
        self.uploads.append(
            {
                "url": url,
                "path": Path(path),
                "headers": dict(headers),
                "timeout": timeout,
            }
        )

    def download_file(self, url, path, *, timeout, max_bytes):
        data = b"fake-mp4-content"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        result = {
            "path": str(path.resolve()),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        self.downloads.append(
            {"url": url, "path": Path(path), "timeout": timeout, "max": max_bytes}
        )
        return result


def settings(output_dir: Path) -> HiggsfieldSettings:
    return HiggsfieldSettings(
        api_key_id="key-id-do-not-print",
        api_key_secret="secret-do-not-print",
        seedance_endpoint="/account/seedance-2",
        output_dir=output_dir,
        generation_timeout_seconds=60,
    )


class HiggsfieldSettingsTests(unittest.TestCase):
    def test_status_reports_presence_without_secret_values(self):
        env = {
            "HIGGSFIELD_API_KEY_ID": "my-key-id",
            "HIGGSFIELD_API_KEY_SECRET": "my-secret",
            "HIGGSFIELD_SEEDANCE_ENDPOINT": "/assigned/seedance",
        }
        result = status(environ=env)
        encoded = json.dumps(result)
        self.assertTrue(result["ready"])
        self.assertNotIn("my-key-id", encoded)
        self.assertNotIn("my-secret", encoded)
        self.assertFalse(result["credential_values_exposed"])

    def test_credentials_must_be_complete_and_api_host_is_pinned(self):
        with self.assertRaisesRegex(HiggsfieldError, "must be set together"):
            HiggsfieldSettings.from_env({"HIGGSFIELD_API_KEY_ID": "only-one"})
        with self.assertRaisesRegex(HiggsfieldError, "api.higgsfield.ai"):
            HiggsfieldSettings.from_env(
                {"HIGGSFIELD_API_BASE_URL": "https://attacker.example"}
            )
        with self.assertRaisesRegex(HiggsfieldError, "relative API path"):
            HiggsfieldSettings.from_env(
                {"HIGGSFIELD_SEEDANCE_ENDPOINT": "https://attacker.example/model"}
            )


class SeedanceValidationTests(unittest.TestCase):
    def test_defaults_and_official_parameter_constraints(self):
        result = normalize_seedance_request({"prompt": "  Product shot  "})
        self.assertEqual(result["prompt"], "Product shot")
        self.assertEqual(result["duration"], 5)
        self.assertEqual(result["resolution"], "720p")
        self.assertEqual(result["mode"], "std")
        with self.assertRaisesRegex(HiggsfieldError, "fast mode"):
            normalize_seedance_request(
                {"prompt": "x", "mode": "fast", "resolution": "4k"}
            )
        with self.assertRaisesRegex(HiggsfieldError, "between 1 and 15"):
            normalize_seedance_request({"prompt": "x", "duration": True})
        with self.assertRaisesRegex(HiggsfieldError, "unsupported"):
            normalize_seedance_request({"prompt": "x", "secret": "wrong"})

    def test_reference_limits_and_audio_requires_visual_input(self):
        with self.assertRaisesRegex(HiggsfieldError, "audio references require"):
            normalize_seedance_request(
                {
                    "prompt": "x",
                    "audio_references": ["https://cdn.example.test/music.wav"],
                }
            )
        with self.assertRaisesRegex(HiggsfieldError, "at most 3 video"):
            normalize_seedance_request(
                {
                    "prompt": "x",
                    "video_references": [
                        f"https://cdn.example.test/{index}.mp4" for index in range(4)
                    ],
                }
            )

    def test_plan_lists_local_uploads_and_never_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "reference.png"
            image.write_bytes(b"png")
            result = build_plan(
                {"prompt": "x", "image_references": [str(image)]},
                settings=HiggsfieldSettings(seedance_endpoint="/assigned"),
            )
            self.assertFalse(result["executes"])
            self.assertTrue(result["paid_operation"])
            self.assertEqual(result["uploads"][0]["path"], str(image.resolve()))
            self.assertFalse(result["credentials_exposed"])


class HiggsfieldClientTests(unittest.TestCase):
    def test_upload_uses_presigned_headers_without_api_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "reference.png"
            image.write_bytes(b"png")
            fake = FakeTransport()
            client = HiggsfieldClient(settings(root / "out"), transport=fake)
            public_url = client.upload(str(image))
            self.assertEqual(public_url, "https://cdn.example.test/input/reference.png")
            self.assertIn("Authorization", fake.requests[0]["headers"])
            self.assertNotIn("Authorization", fake.uploads[0]["headers"])
            self.assertEqual(fake.uploads[0]["path"], image)

    def test_authenticated_status_urls_are_restricted_to_official_host(self):
        with tempfile.TemporaryDirectory() as directory:
            client = HiggsfieldClient(
                settings(Path(directory)), transport=FakeTransport()
            )
            with self.assertRaisesRegex(HiggsfieldError, "outside api.higgsfield.ai"):
                client.get_status("https://attacker.example/steal")

    def test_paid_generate_uploads_polls_downloads_hashes_and_builds_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "reference.png"
            image.write_bytes(b"png")
            fake = FakeTransport()
            result = generate_seedance(
                {
                    "prompt": "Precise black product shot",
                    "duration": 10,
                    "resolution": "1080p",
                    "image_references": [str(image)],
                },
                acknowledge_paid_generation=True,
                settings=settings(root / "out"),
                transport=fake,
                sleep=lambda _: None,
                monotonic=lambda: 0.0,
                jitter=lambda _a, _b: 0.0,
            )
            output = Path(result["download"]["path"])
            manifest = Path(result["manifest_path"])
            self.assertTrue(output.is_file())
            self.assertTrue(manifest.is_file())
            self.assertEqual(fake.status_calls, 2)
            self.assertEqual(
                result["download"]["sha256"],
                hashlib.sha256(b"fake-mp4-content").hexdigest(),
            )
            self.assertEqual(result["handoff"]["video_path"], str(output))
            submitted_payload = next(
                call["payload"]
                for call in fake.requests
                if call["url"].endswith("/account/seedance-2")
            )
            self.assertEqual(
                submitted_payload["image_references"],
                ["https://cdn.example.test/input/reference.png"],
            )

    def test_paid_generate_requires_explicit_acknowledgement_before_network(self):
        fake = FakeTransport()
        with self.assertRaisesRegex(HiggsfieldError, "acknowledge_paid_generation"):
            generate_seedance(
                {"prompt": "x"},
                acknowledge_paid_generation=False,
                settings=settings(Path("out/test")),
                transport=fake,
            )
        self.assertEqual(fake.requests, [])

    def test_submit_only_returns_async_request_without_download(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeTransport()
            result = generate_seedance(
                {"prompt": "x"},
                acknowledge_paid_generation=True,
                wait=False,
                settings=settings(Path(directory) / "out"),
                transport=fake,
            )
            self.assertEqual(result["submitted"]["status"], "queued")
            self.assertIsNone(result["download"])
            self.assertEqual(fake.status_calls, 0)
            self.assertEqual(fake.downloads, [])


if __name__ == "__main__":
    unittest.main()
