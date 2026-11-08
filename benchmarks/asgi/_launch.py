#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Run a module with a given gunicorn source tree first on sys.path.

    python _launch.py <gunicorn-root> <module> [args...]

An editable install wins over PYTHONPATH, so a benchmark of another
revision (a git worktree) would silently import the installed tree. This
puts <gunicorn-root> first, then runs <module> as __main__.
"""

import os
import runpy
import sys


def main():
    root, module = sys.argv[1], sys.argv[2]
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # apps.py
    sys.path.insert(0, os.path.abspath(root))
    for name in [m for m in sys.modules if m == "gunicorn" or m.startswith("gunicorn.")]:
        del sys.modules[name]
    sys.argv = [module] + sys.argv[3:]
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
