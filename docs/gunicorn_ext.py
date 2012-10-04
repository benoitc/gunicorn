import os
import inspect
import gunicorn.config as guncfg

HEAD = """
Settings
========

This is an exhaustive list of settings for Gunicorn. Some settings are only
able to be set from a configuration file. The setting name is what should be
used in the configuration file. The command line arguments are listed as well
for reference on setting at the command line.

"""

def format_settings(app):
    settings_file = os.path.join(app.srcdir, "settings.rst")
    ret = []
    for i, s in enumerate(guncfg.KNOWN_SETTINGS):
        if i == 0 or s.section != guncfg.KNOWN_SETTINGS[i - 1].section:
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
    else:
        val = "``%s``" % s.default

    if s.cli and s.meta:
        args = ["%s %s" % (arg, s.meta) for arg in s.cli]
        cli = ', '.join(args)
    elif s.cli:
        cli = ", ".join(s.cli)

    out = []
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

def setup(app):
    app.connect('builder-inited', format_settings)
