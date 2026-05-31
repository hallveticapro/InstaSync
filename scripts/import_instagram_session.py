from __future__ import annotations

import argparse
import getpass
import json
import os
import pickle
import tempfile
from pathlib import Path
from typing import Mapping


COOKIE_NAMES = ("sessionid", "csrftoken", "ds_user_id", "mid", "ig_did")
COOKIE_ENV_NAMES = {
    name: f"INSTAGRAM_{name.upper()}"
    for name in COOKIE_NAMES
}


def cookies_from_environment(environ: Mapping[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, env_name in COOKIE_ENV_NAMES.items()
        if (value := environ.get(env_name, "").strip())
    }


def cookies_from_json_file(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("cookie JSON file must contain an object")
    return {
        name: value.strip()
        for name in COOKIE_NAMES
        if isinstance((value := data.get(name)), str) and value.strip()
    }


def prompt_for_cookies() -> dict[str, str]:
    cookies: dict[str, str] = {}
    for name in COOKIE_NAMES:
        suffix = " (required)" if name == "sessionid" else " (optional)"
        value = getpass.getpass(f"{name}{suffix}: ").strip()
        if value:
            cookies[name] = value
    return cookies


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
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument(
        "--from-env",
        action="store_true",
        help="Read cookies from INSTAGRAM_SESSIONID and optional INSTAGRAM_* variables.",
    )
    input_group.add_argument(
        "--cookies-json-file",
        type=Path,
        help="Read cookies from a mounted JSON secret file.",
    )
    args = parser.parse_args()

    if args.from_env:
        cookies = cookies_from_environment(os.environ)
    elif args.cookies_json_file:
        cookies = cookies_from_json_file(args.cookies_json_file)
    else:
        cookies = prompt_for_cookies()

    write_session_file(args.output, cookies)
    print(f"Saved Instaloader session cookies to {args.output}")


if __name__ == "__main__":
    main()
