#!/usr/bin/env python
# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from __future__ import with_statement

import codecs
import datetime
import inspect
import os
import subprocess as sp
import sys

from docutils.core import publish_parts
from jinja2 import Environment
from jinja2.loaders import FileSystemLoader
from jinja2.utils import open_if_exists

from sitemap_gen import CreateSitemapFromFile
import conf

class Site(object):
    def __init__(self):
        self.url = conf.SITE_URL.rstrip('/')

        fs_loader = FileSystemLoader(conf.TEMPLATES_PATH, encoding="utf-8")
        self.env = Environment(loader=fs_loader)
        self.env.charset = 'utf-8'
        self.env.filters['rel_url'] = self.rel_url

    def rel_url(self, value):
        return value.split(self.url)[1]

    def render(self):
        for curr_path, dirs, files in os.walk(conf.INPUT_PATH):
            tgt_path = curr_path.replace(conf.INPUT_PATH, conf.OUTPUT_PATH)
            if not os.path.isdir(tgt_path):
                os.makedirs(tgt_path)
            self.process(files, curr_path, tgt_path)
        self.sass_compile()

    def process(self, files, curr_path, tgt_path):
        for f in files:
            page = Page(self, f, curr_path, tgt_path)
            if not page.needed():
                continue

            print("Page: %s" % page.source)
            page.write()

    def sass_compile(self):
        print("")
        print("Updating css...")
        try:
            sp.check_call(["compass", "compile", "--boring"])
        except sp.CalledProcessError:
            sys.stderr.write("Failed to update CSS")
            sys.stderr.flush()

    def get_template(self, name):
        return self.env.get_template(name)

class Page(object):

    def __init__(self, site, filename, curr_path, tgt_path):
        self.site = site
        self.filename = filename
        self.source = os.path.join(curr_path, filename)
        self.headers = {}
        self.body = ""

        with open(self.source, 'Ur') as handle:
            raw = handle.read()

        try:
            headers, body = raw.split("\n\n", 1)
        except ValueError:
            headers, body = "", raw

        try:
            for line in headers.splitlines():
                name, value = line.split(':', 1)
                self.headers[name.strip()] = value.strip()
        except ValueError:
            self.headers = {}
            body = "\n\n".join([headers, body])
        self.headers['pubDate'] = ctime = os.stat(self.source).st_ctime
        self.headers['published'] = datetime.datetime.fromtimestamp(ctime)

        basename, oldext = os.path.splitext(filename)
        oldext = oldext.lower()[1:]
        converter = getattr(self, "convert_%s" % oldext, lambda x: (None, x))
        if "insert_settings" in self.headers:
            body = body % {"settings": self.format_settings()}
        self.toc, self.body = converter(body)

        newext = self.headers.get('ext', '.html')
        self.target = os.path.join(tgt_path, "%s%s" % (basename, newext))

    def url(self):
        path = self.target.split(conf.OUTPUT_PATH)[1].lstrip('/')
        return "/".join([self.site.url, path])

    def needed(self):
        for f in "force --force -f".split():
            if f in sys.argv[1:]:
                return True

        if not os.path.exists(self.target):
            return True

        smtime = os.stat(self.source).st_mtime
        tmtime = os.stat(self.target).st_mtime
        return smtime > tmtime

    def write(self):
        contents = self.render()
        with codecs.open(self.target, 'w', 'utf-8') as tgt:
            tgt.write(contents)

    def render(self):
        tmpl_name = self.headers.get('template')
        if not tmpl_name:
            return self.body

        kwargs = {
            "conf": conf,
            "toc": self.toc,
            "body": self.body,
            "url": self.url()
        }
        kwargs.update(self.headers)
        return self.site.get_template(tmpl_name).render(kwargs)

    def convert_rst(self, body):
        overrides = {"initial_header_level": 2}
        parts = publish_parts(
            source=body,
            writer_name="html",
            settings_overrides=overrides
        )
        lines = parts['html_body'].splitlines()

        toppos, botpos = None, None
        for idx, line in enumerate(lines):
            if line.find("_TOC_TOP_") >= 0:
                toppos = idx
            elif line.find("_TOC_BOT_") >= 0:
                botpos = idx

        if toppos is None or botpos is None:
            return None, parts['html_body']

        toc = lines[toppos+1:botpos]
        body = lines[:toppos] + lines[botpos+1:]
        return '\n'.join(toc), '\n'.join(body)

    def format_settings(self):
        currdir = os.path.dirname(__file__)
        sys.path.insert(0, os.path.join(currdir, ".."))
        import gunicorn.config as guncfg
        ret = []
        for i, s in enumerate(guncfg.KNOWN_SETTINGS):
            if i == 0 or s.section != guncfg.KNOWN_SETTINGS[i-1].section:
                ret.append("%s\n%s\n\n" % (s.section, "+" * len(s.section)))
            ret.append(self.fmt_setting(s))
        return ''.join(ret)

    def fmt_setting(self, s):
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

def main():
    Site().render()

if __name__ == "__main__":
    main()
