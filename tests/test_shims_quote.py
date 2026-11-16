"""Exec= quoting of the wrapper path (Desktop Entry spec: double quotes
around an argument with a reserved character, a backslash before " ` $ and
backslash inside, the string-value escape on top, %% for a literal %)."""

import re
import unittest

from fixtures.sandbox import fixture  # noqa: F401  (sets sys.path)
from appglass import shims


def unquote(word):
    """What a launcher hands execve, one argument: undo the string-value
    escape, then the double quotes and their escapes, then %%."""
    word = re.sub(r"\\(.)", r"\1", word)
    if word.startswith('"'):
        assert len(word) > 1 and word.endswith('"'), word
        word = re.sub(r'\\(["`$\\])', r"\1", word[1:-1])
    return word.replace("%%", "%")


class Quote(unittest.TestCase):
    def test_plain_path_unchanged(self):
        self.assertEqual(shims.desktop_quote("/home/u/.local/bin/appglass-x"),
                         "/home/u/.local/bin/appglass-x")

    def test_round_trip(self):
        for p in ("/home/my user/bin/w", "/h/a$b", '/h/a"b', "/h/a`b", "/h/a\\b",
                  "/h/100%/w", "/h/a'b", "/h/(x)&y;z|<>~*?#"):
            q = shims.desktop_quote(p)
            self.assertEqual(unquote(q), p, q)
            if p != "/h/100%/w":
                self.assertTrue(q.startswith('"') and q.endswith('"'), q)

    def test_line_break_refused(self):
        with self.assertRaises(ValueError):
            shims.desktop_quote("/h/a\nExec=evil")

    def test_exec_to_quotes_the_wrapper(self):
        text = "[Desktop Entry]\nExec=/usr/bin/app %U\n"
        out = shims.exec_to(text, "/home/my user/.local/bin/appglass-app", command="app")
        self.assertEqual(out, '[Desktop Entry]\nExec="/home/my user/.local/bin/appglass-app" %U\n')


if __name__ == "__main__":
    unittest.main()
