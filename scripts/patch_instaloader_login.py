from __future__ import annotations

import inspect
from pathlib import Path

from instaloader.instaloadercontext import InstaloaderContext

EMPTY_SESSION_COOKIE = "'sessionid': '', "
LOGIN_START = "    def login(self, user, passwd):"
LOGIN_END = "    def two_factor_login"


def patch_instaloader_login(source: str) -> str:
    login_start = source.find(LOGIN_START)
    login_end = source.find(LOGIN_END, login_start)
    if login_start == -1 or login_end == -1:
        raise RuntimeError("Unable to locate Instaloader login source")

    login_source = source[login_start:login_end]
    if EMPTY_SESSION_COOKIE not in login_source:
        raise RuntimeError("Instaloader login source did not contain the expected sessionid seed")
    patched_login_source = login_source.replace(EMPTY_SESSION_COOKIE, "", 1)
    return source[:login_start] + patched_login_source + source[login_end:]


def main() -> None:
    source_path = Path(inspect.getsourcefile(InstaloaderContext) or "")
    if not source_path.is_file():
        raise RuntimeError("Unable to locate InstaloaderContext source")

    source = source_path.read_text(encoding="utf-8")
    source_path.write_text(patch_instaloader_login(source), encoding="utf-8")


if __name__ == "__main__":
    main()
