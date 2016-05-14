import os

from gunicorn.lockfile import LockFile
from gunicorn.util import tmpfile

def test_lockfile():
    lockname = tmpfile(prefix="gunicorn-tests", suffix=".lock")
    lock_file = LockFile(lockname)
    assert lock_file.locked() == False
    assert os.path.exists(lockname)
    lock_file.lock()
    assert lock_file.locked() == True
    lock_file.unlock()
    assert lock_file.locked() == False
    assert os.path.exists(lockname) == False
