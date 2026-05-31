from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import (
    INSTAGRAM_PROFILE_INFO_URL,
    InstaloaderProfileResolver,
    ProfileNotFound,
    Settings,
    UpstreamError,
    create_app,
)

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"profile-picture"
INSTALOADER_HD_URL = "https://scontent.example.cdninstagram.com/instaloader-hd.jpg?signed=1"
HD_URL = "https://scontent.example.cdninstagram.com/profile-hd.jpg?signed=1"
SMALL_URL = "https://scontent.example.cdninstagram.com/profile-small.jpg?signed=1"


@dataclass
class FakeResponse:
    status_code: int = 200
    json_data: Any = None
    content: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self) -> Any:
        if isinstance(self.json_data, Exception):
            raise self.json_data
        return self.json_data

    def iter_content(self, chunk_size: int) -> list[bytes]:
        return [self.content]

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = deque(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        assert self.responses, f"Unexpected GET request for {url}"
        return self.responses.popleft()


class FakeInstaloaderResolver:
    def __init__(
        self,
        image_url: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.image_url = image_url
        self.error = error or UpstreamError("Instaloader lookup failed")
        self.calls: list[str] = []

    def get_profile_image_url(self, username: str) -> str:
        self.calls.append(username)
        if self.image_url:
            return self.image_url
        raise self.error


def metadata_response(
    *,
    hd_url: str | None = HD_URL,
    small_url: str | None = SMALL_URL,
    private: bool = False,
) -> FakeResponse:
    return FakeResponse(
        json_data={
            "data": {
                "user": {
                    "is_private": private,
                    "profile_pic_url_hd": hd_url,
                    "profile_pic_url": small_url,
                }
            }
        }
    )


def image_response(content: bytes = JPEG_BYTES) -> FakeResponse:
    return FakeResponse(content=content, headers={"Content-Type": "image/jpeg"})


def test_healthcheck(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path, [])

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_instaloader_image_is_preferred_and_username_is_normalized(
    tmp_path: Path,
) -> None:
    resolver = FakeInstaloaderResolver(image_url=INSTALOADER_HD_URL)
    client, session = make_client(tmp_path, [image_response()], resolver)

    response = client.get("/insta/InStaGram")

    assert response.status_code == 200
    assert response.content == JPEG_BYTES
    assert response.headers["x-cache"] == "MISS"
    assert resolver.calls == ["instagram"]
    assert session.calls[0][0] == INSTALOADER_HD_URL


def test_web_profile_info_hd_image_is_used_when_instaloader_fails(
    tmp_path: Path,
) -> None:
    client, session = make_client(tmp_path, [metadata_response(), image_response()])

    response = client.get("/insta/instagram")

    assert response.status_code == 200
    assert session.calls[0][0] == INSTAGRAM_PROFILE_INFO_URL
    assert session.calls[0][1]["params"] == {"username": "instagram"}
    assert session.calls[1][0] == HD_URL


def test_small_image_is_used_when_hd_url_is_absent(tmp_path: Path) -> None:
    client, session = make_client(
        tmp_path, [metadata_response(hd_url=None), image_response()]
    )

    response = client.get("/insta/instagram")

    assert response.status_code == 200
    assert session.calls[1][0] == SMALL_URL


def test_fresh_cached_image_is_returned_without_refresh(tmp_path: Path) -> None:
    client, session = make_client(tmp_path, [metadata_response(), image_response()])
    assert client.get("/insta/instagram").headers["x-cache"] == "MISS"

    response = client.get("/insta/instagram")

    assert response.status_code == 200
    assert response.headers["x-cache"] == "HIT"
    assert len(session.calls) == 2


def test_expired_cached_image_is_refreshed(tmp_path: Path) -> None:
    client, session = make_client(
        tmp_path,
        [metadata_response(), image_response(), metadata_response(), image_response()],
    )
    assert client.get("/insta/instagram").status_code == 200
    expire_cache(tmp_path, "instagram")

    response = client.get("/insta/instagram")

    assert response.status_code == 200
    assert response.headers["x-cache"] == "MISS"
    assert len(session.calls) == 4


def test_stale_cached_image_is_returned_when_refresh_fails(tmp_path: Path) -> None:
    client, _ = make_client(
        tmp_path,
        [metadata_response(), image_response(), FakeResponse(status_code=503)],
    )
    assert client.get("/insta/instagram").status_code == 200
    expire_cache(tmp_path, "instagram")

    response = client.get("/insta/instagram")

    assert response.status_code == 200
    assert response.content == JPEG_BYTES
    assert response.headers["x-cache"] == "STALE"


def test_invalid_username_is_rejected_without_upstream_request(tmp_path: Path) -> None:
    client, session = make_client(tmp_path, [])

    response = client.get("/insta/invalid..username")

    assert response.status_code == 400
    assert session.calls == []


def test_missing_profile_returns_404(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path, [FakeResponse(status_code=404)])

    response = client.get("/insta/notfound")

    assert response.status_code == 404


def test_private_profile_returns_404(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path, [metadata_response(private=True)])

    response = client.get("/insta/privateprofile")

    assert response.status_code == 404


def test_malformed_upstream_response_returns_502(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path, [FakeResponse(json_data={"data": {}})])

    response = client.get("/insta/instagram")

    assert response.status_code == 502


def test_unrecognized_image_bytes_return_502(tmp_path: Path) -> None:
    client, _ = make_client(
        tmp_path, [metadata_response(), image_response(content=b"not-an-image")]
    )

    response = client.get("/insta/instagram")

    assert response.status_code == 502


def test_instaloader_resolver_uses_best_profile_picture_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = SimpleNamespace(is_private=False, profile_pic_url=INSTALOADER_HD_URL)
    monkeypatch.setattr(
        "app.main.InstaloaderProfile.from_username",
        lambda context, username: profile,
    )
    resolver = InstaloaderProfileResolver(loader=SimpleNamespace(context=object()))

    assert resolver.get_profile_image_url("instagram") == INSTALOADER_HD_URL


def test_instaloader_private_profile_does_not_use_fallback(tmp_path: Path) -> None:
    resolver = FakeInstaloaderResolver(error=ProfileNotFound("privateprofile"))
    client, session = make_client(tmp_path, [], resolver)

    response = client.get("/insta/privateprofile")

    assert response.status_code == 404
    assert session.calls == []


def make_client(
    tmp_path: Path,
    responses: list[FakeResponse],
    resolver: FakeInstaloaderResolver | None = None,
) -> tuple[TestClient, FakeSession]:
    session = FakeSession(responses)
    settings = Settings(cache_dir=tmp_path, cache_ttl_seconds=86400)
    return TestClient(create_app(settings, session, resolver or FakeInstaloaderResolver())), session


def expire_cache(tmp_path: Path, username: str) -> None:
    metadata_path = tmp_path / f"{username}.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["fetched_at"] = 0
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
