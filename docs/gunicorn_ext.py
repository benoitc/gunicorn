import os
import inspect

from docutils import nodes, utils

import gunicorn.config as guncfg

HEAD = """\
.. Please update gunicorn/config.py instead.

.. _settings:

Settings
========

This is an exhaustive list of settings for Gunicorn. Some settings are only
able to be set from a configuration file. The setting name is what should be
used in the configuration file. The command line arguments are listed as well
for reference on setting at the command line.

.. note::

    Settings can be specified by using environment variable
    ``GUNICORN_CMD_ARGS``. All available command line arguments can be used.
    For example, to specify the bind address and number of workers::

        $ GUNICORN_CMD_ARGS="--bind=127.0.0.1 --workers=3" gunicorn app:app

    .. versionadded:: 19.7

"""
ISSUE_URI = 'https://github.com/benoitc/gunicorn/issues/%s'
PULL_REQUEST_URI = 'https://github.com/benoitc/gunicorn/pull/%s'


def format_settings(app):
    settings_file = os.path.join(app.srcdir, "settings.rst")
    ret = []
    known_settings = sorted(guncfg.KNOWN_SETTINGS, key=lambda s: s.section)
    for i, s in enumerate(known_settings):
        if i == 0 or s.section != known_settings[i - 1].section:
            ret.append("%s\n%s\n\n" % (s.section, "-" * len(s.section)))
        ret.append(fmt_setting(s))

    with open(settings_file, 'w') as settings:
        settings.write(HEAD)
        settings.write(''.join(ret))


def fmt_setting(s):
    if callable(s.default):
        val = inspect.getsource(s.default)
        val = "\n".join("    %s" % l for l in val.splitlines())
        val = " ::\n\n" + val
    elif s.default == '':
        val = "``(empty string)``"
    else:
        val = "``%s``" % s.default

    if s.cli and s.meta:
        args = ["%s %s" % (arg, s.meta) for arg in s.cli]
        cli = ', '.join(args)
    elif s.cli:
        cli = ", ".join(s.cli)

    out = []
    out.append(".. _%s:\n" % s.name.replace("_", "-"))
    out.append("%s" % s.name)
    out.append("~" * len(s.name))
    out.append("")
    if s.cli:
        out.append("* ``%s``" % cli)
    out.append("* %s" % val)
    out.append("")
    out.append(s.desc)
    out.append("")
    out.append("")
    return "\n".join(out)


def issue_role(typ, rawtext, text, lineno, inliner, options={}, content=[]):
    issue = utils.unescape(text)
    text = 'issue ' + issue
    refnode = nodes.reference(text, text, refuri=ISSUE_URI % issue)
    return [refnode], []


def pull_request_role(typ, rawtext, text, lineno, inliner, options={}, content=[]):
    issue = utils.unescape(text)
    text = 'pull request ' + issue
    refnode = nodes.reference(text, text, refuri=PULL_REQUEST_URI % issue)
    return [refnode], []


def setup(app):
    app.connect('builder-inited', format_settings)
    app.add_role('issue', issue_role)
    app.add_role('pr', pull_request_role)
