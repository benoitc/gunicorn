import os

from gunicorn.lockfile import LockFile
from gunicorn.util import tmpfile

def test_lockfile():
    lockname = tmpfile(prefix="gunicorn-tests", suffix=".lock")
    lock_file = LockFile(lockname)
    assert lock_file.released() == True
    assert os.path.exists(lockname)
    lock_file.acquire()
    assert lock_file.released() == False
    lock_file.release()
    assert lock_file.released() == True
    assert os.path.exists(lockname) == False
