from scripts.patch_instaloader_login import patch_instaloader_login


def test_patch_instaloader_login_removes_empty_session_cookie_seed() -> None:
    source = """\
    def get_anonymous_session(self):
        session.cookies.update({'sessionid': '', 'mid': '', 'ig_pr': '1'})

    def login(self, user, passwd):
        session.cookies.update({'sessionid': '', 'mid': '', 'ig_pr': '1'})

    def two_factor_login(self, two_factor_code):
        pass
"""

    patched = patch_instaloader_login(source)

    assert patched == """\
    def get_anonymous_session(self):
        session.cookies.update({'sessionid': '', 'mid': '', 'ig_pr': '1'})

    def login(self, user, passwd):
        session.cookies.update({'mid': '', 'ig_pr': '1'})

    def two_factor_login(self, two_factor_code):
        pass
"""
