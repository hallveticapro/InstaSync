from scripts.patch_instaloader_login import patch_instaloader_login


def test_patch_instaloader_login_removes_empty_session_cookie_seed() -> None:
    source = "session.cookies.update({'sessionid': '', 'mid': '', 'ig_pr': '1'})"

    patched = patch_instaloader_login(source)

    assert patched == "session.cookies.update({'mid': '', 'ig_pr': '1'})"
