from __future__ import annotations

import inspect
from pathlib import Path

from instaloader.instaloadercontext import InstaloaderContext

EMPTY_SESSION_COOKIE = "'sessionid': '', "


def patch_instaloader_login(source: str) -> str:
    if EMPTY_SESSION_COOKIE not in source:
        raise RuntimeError("Instaloader login source did not contain the expected sessionid seed")
    return source.replace(EMPTY_SESSION_COOKIE, "", 1)


def main() -> None:
    source_path = Path(inspect.getsourcefile(InstaloaderContext) or "")
    if not source_path.is_file():
        raise RuntimeError("Unable to locate InstaloaderContext source")

    source = source_path.read_text(encoding="utf-8")
    source_path.write_text(patch_instaloader_login(source), encoding="utf-8")


if __name__ == "__main__":
    main()
