from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

INSTAGRAM_PROFILE_INFO_URL = "https://www.instagram.com/api/v1/users/web_profile_info/"
DEFAULT_INSTAGRAM_APP_ID = "936619743392459"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
USERNAME_PATTERN = re.compile(r"^(?!\.)(?!.*\.\.)(?!.*\.$)[a-z0-9._]{1,30}$")
ALLOWED_IMAGE_HOST_SUFFIXES = ("cdninstagram.com", "fbcdn.net")
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


class ProfileNotFound(Exception):
    """Raised when Instagram does not expose a requested public profile."""


class UpstreamError(Exception):
    """Raised when Instagram or its CDN cannot provide a usable image."""


class CacheError(Exception):
    """Raised when a cache file cannot be stored."""


def _positive_int_from_env(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _positive_float_from_env(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True)
class Settings:
    cache_dir: Path = field(
        default_factory=lambda: Path(os.getenv("CACHE_DIR", "/data/cache"))
    )
    cache_ttl_seconds: int = field(
        default_factory=lambda: _positive_int_from_env("CACHE_TTL_SECONDS", 86400)
    )
    instagram_app_id: str = field(
        default_factory=lambda: os.getenv("INSTAGRAM_APP_ID", DEFAULT_INSTAGRAM_APP_ID)
    )
    request_timeout_seconds: float = field(
        default_factory=lambda: _positive_float_from_env("REQUEST_TIMEOUT_SECONDS", 15.0)
    )
    max_image_bytes: int = field(
        default_factory=lambda: _positive_int_from_env(
            "MAX_IMAGE_BYTES", 10 * 1024 * 1024
        )
    )


@dataclass(frozen=True)
class CacheEntry:
    path: Path
    content_type: str
    fetched_at: float


def normalize_username(username: str) -> str:
    normalized = username.strip().lower()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("Invalid Instagram username")
    return normalized


def _detect_image_type(prefix: bytes) -> str | None:
    if prefix.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP":
        return "image/webp"
    return None


def _is_allowed_image_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    hostname = parsed.hostname.lower()
    return any(
        hostname == suffix or hostname.endswith(f".{suffix}")
        for suffix in ALLOWED_IMAGE_HOST_SUFFIXES
    )


class ProfileImageService:
    def __init__(
        self,
        settings: Settings,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def get_profile_image(self, username: str) -> tuple[CacheEntry, str]:
        entry = self._read_cache_entry(username)
        if entry and self._is_fresh(entry):
            return entry, "HIT"

        with self._lock_for(username):
            entry = self._read_cache_entry(username)
            if entry and self._is_fresh(entry):
                return entry, "HIT"

            try:
                return self._refresh(username), "MISS"
            except ProfileNotFound:
                raise
            except UpstreamError:
                stale_entry = self._read_cache_entry(username)
                if stale_entry:
                    logger.warning(
                        "Serving stale cached image for %s after refresh failure",
                        username,
                        exc_info=True,
                    )
                    return stale_entry, "STALE"
                raise

    def _refresh(self, username: str) -> CacheEntry:
        image_url = self._get_profile_image_url(username)
        return self._download_image(username, image_url)

    def _get_profile_image_url(self, username: str) -> str:
        try:
            response = self.session.get(
                INSTAGRAM_PROFILE_INFO_URL,
                params={"username": username},
                headers={
                    "X-IG-App-ID": self.settings.instagram_app_id,
                    "User-Agent": DEFAULT_USER_AGENT,
                },
                timeout=self.settings.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise UpstreamError("Instagram metadata request failed") from exc

        if response.status_code == 404:
            raise ProfileNotFound(username)
        if not response.ok:
            raise UpstreamError(
                f"Instagram metadata request returned {response.status_code}"
            )

        try:
            user = response.json()["data"]["user"]
        except (KeyError, TypeError, ValueError) as exc:
            raise UpstreamError("Instagram metadata response was malformed") from exc

        if not isinstance(user, dict):
            raise UpstreamError("Instagram metadata response did not contain a profile")
        if user.get("is_private"):
            raise ProfileNotFound(username)

        image_url = user.get("profile_pic_url_hd") or user.get("profile_pic_url")
        if not isinstance(image_url, str) or not _is_allowed_image_url(image_url):
            raise UpstreamError("Instagram metadata response did not contain a safe image URL")
        return image_url

    def _download_image(self, username: str, image_url: str) -> CacheEntry:
        image_path = self.settings.cache_dir / f"{username}.image"
        metadata_path = self.settings.cache_dir / f"{username}.json"
        temporary_image_path: Path | None = None
        temporary_metadata_path: Path | None = None

        try:
            self.settings.cache_dir.mkdir(parents=True, exist_ok=True)
            with self.session.get(
                image_url,
                stream=True,
                timeout=self.settings.request_timeout_seconds,
            ) as response:
                if not response.ok:
                    raise UpstreamError(
                        f"Instagram image request returned {response.status_code}"
                    )

                fd, temporary_name = tempfile.mkstemp(
                    dir=self.settings.cache_dir,
                    prefix=f".{username}.",
                    suffix=".image.tmp",
                )
                temporary_image_path = Path(temporary_name)
                size = 0
                prefix = b""
                with os.fdopen(fd, "wb") as temporary_file:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > self.settings.max_image_bytes:
                            raise UpstreamError("Instagram image exceeded maximum size")
                        if len(prefix) < 12:
                            prefix = (prefix + chunk)[:12]
                        temporary_file.write(chunk)

                detected_type = _detect_image_type(prefix)
                response_type = response.headers.get("Content-Type", "").split(";", 1)[
                    0
                ].lower()
                if detected_type not in SUPPORTED_IMAGE_TYPES:
                    raise UpstreamError("Instagram image format was not recognized")
                if response_type and response_type not in {detected_type, "image/jpg"}:
                    raise UpstreamError("Instagram image content type did not match its bytes")

            fetched_at = time.time()
            os.replace(temporary_image_path, image_path)
            temporary_image_path = None

            fd, temporary_name = tempfile.mkstemp(
                dir=self.settings.cache_dir,
                prefix=f".{username}.",
                suffix=".json.tmp",
            )
            temporary_metadata_path = Path(temporary_name)
            with os.fdopen(fd, "w", encoding="utf-8") as temporary_file:
                json.dump(
                    {"content_type": detected_type, "fetched_at": fetched_at},
                    temporary_file,
                )
            os.replace(temporary_metadata_path, metadata_path)
            temporary_metadata_path = None
            return CacheEntry(image_path, detected_type, fetched_at)
        except requests.RequestException as exc:
            raise UpstreamError("Instagram image request failed") from exc
        except OSError as exc:
            raise CacheError("Unable to write cached profile picture") from exc
        finally:
            for temporary_path in (temporary_image_path, temporary_metadata_path):
                if temporary_path:
                    temporary_path.unlink(missing_ok=True)

    def _read_cache_entry(self, username: str) -> CacheEntry | None:
        image_path = self.settings.cache_dir / f"{username}.image"
        metadata_path = self.settings.cache_dir / f"{username}.json"
        try:
            if not image_path.is_file() or image_path.stat().st_size == 0:
                return None

            metadata: dict[str, Any] = {}
            if metadata_path.is_file():
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    logger.warning("Ignoring malformed cache metadata for %s", username)

            content_type = metadata.get("content_type")
            if content_type not in SUPPORTED_IMAGE_TYPES:
                with image_path.open("rb") as cached_image:
                    content_type = _detect_image_type(cached_image.read(12))
            if content_type not in SUPPORTED_IMAGE_TYPES:
                return None

            fetched_at = metadata.get("fetched_at", image_path.stat().st_mtime)
            return CacheEntry(image_path, content_type, float(fetched_at))
        except (OSError, TypeError, ValueError):
            logger.warning("Ignoring unreadable cache entry for %s", username)
            return None

    def _is_fresh(self, entry: CacheEntry) -> bool:
        return time.time() - entry.fetched_at < self.settings.cache_ttl_seconds

    def _lock_for(self, username: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(username, threading.Lock())


def create_app(
    settings: Settings | None = None,
    session: requests.Session | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    service = ProfileImageService(resolved_settings, session)
    application = FastAPI(title="InstaSync", version="1.0.0")

    @application.get("/healthz")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/insta/{username}")
    def get_instagram_profile_picture(username: str) -> FileResponse:
        try:
            normalized_username = normalize_username(username)
            entry, cache_status = service.get_profile_image(normalized_username)
            return FileResponse(
                entry.path,
                media_type=entry.content_type,
                headers={"X-Cache": cache_status},
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ProfileNotFound as exc:
            raise HTTPException(status_code=404, detail="Profile not found") from exc
        except UpstreamError as exc:
            logger.warning("Unable to fetch profile picture for %s: %s", username, exc)
            raise HTTPException(
                status_code=502,
                detail="Unable to fetch profile picture from Instagram",
            ) from exc
        except CacheError as exc:
            logger.error("Unable to cache profile picture for %s: %s", username, exc)
            raise HTTPException(
                status_code=500,
                detail="Unable to cache profile picture",
            ) from exc

    return application


app = create_app()
