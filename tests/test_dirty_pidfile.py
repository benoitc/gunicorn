#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""The dirty arbiter PID file lives in the shared temporary directory, so it
is only written and trusted when this user owns it."""

import os
import stat

from gunicorn.dirty.pidfile import write_pidfile, read_trusted_pid


def test_written_with_mode_0600(tmp_path):
    path = str(tmp_path / "p.pid")
    assert write_pidfile(path, 4242) is True
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert read_trusted_pid(path) == 4242


def test_replaces_stale_file_of_ours(tmp_path):
    path = str(tmp_path / "p.pid")
    write_pidfile(path, 1111)
    assert write_pidfile(path, 2222) is True
    assert read_trusted_pid(path) == 2222


def test_does_not_follow_planted_symlink(tmp_path):
    target = tmp_path / "victim"
    target.write_text("keep")
    path = str(tmp_path / "p.pid")
    os.symlink(str(target), path)
    assert write_pidfile(path, 4242) is False
    assert target.read_text() == "keep"
    assert read_trusted_pid(path) is None


def test_untrusted_content(tmp_path):
    path = tmp_path / "p.pid"
    for content in ("", "abc", "-1", "0", str(os.getpid())):
        path.write_text(content)
        os.chmod(path, 0o600)
        assert read_trusted_pid(str(path)) is None, content
