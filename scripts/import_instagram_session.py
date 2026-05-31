from __future__ import annotations

import argparse
import getpass
import os
import pickle
import tempfile
from pathlib import Path


COOKIE_NAMES = ("sessionid", "csrftoken", "ds_user_id", "mid", "ig_did")


def write_session_file(path: Path, cookies: dict[str, str]) -> None:
    if not cookies.get("sessionid"):
        raise ValueError("sessionid is required")

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as session_file:
            pickle.dump(cookies, session_file)
        temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create an Instaloader session file from Instagram browser cookies."
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Session file path, such as /data/session-hallveticapro.",
    )
    args = parser.parse_args()

    cookies: dict[str, str] = {}
    for name in COOKIE_NAMES:
        suffix = " (required)" if name == "sessionid" else " (optional)"
        value = getpass.getpass(f"{name}{suffix}: ").strip()
        if value:
            cookies[name] = value

    write_session_file(args.output, cookies)
    print(f"Saved Instaloader session cookies to {args.output}")


if __name__ == "__main__":
    main()
