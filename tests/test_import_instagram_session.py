from __future__ import annotations

import pickle
import stat
from pathlib import Path

import pytest

from scripts.import_instagram_session import write_session_file


def test_write_session_file_persists_cookies_with_private_permissions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "session-hallveticapro"

    write_session_file(path, {"sessionid": "secret", "csrftoken": "csrf"})

    with path.open("rb") as session_file:
        assert pickle.load(session_file) == {
            "sessionid": "secret",
            "csrftoken": "csrf",
        }
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_write_session_file_requires_sessionid(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sessionid is required"):
        write_session_file(tmp_path / "session-hallveticapro", {"csrftoken": "csrf"})
