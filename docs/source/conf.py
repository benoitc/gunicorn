# -*- coding: utf-8 -*-
#
# Gunicorn documentation build configuration file
#

import os
import sys
import time

DOCS_DIR = os.path.abspath(os.path.dirname(__file__))

on_rtd = os.environ.get('READTHEDOCS', None) == 'True'

# for gunicorn_ext.py
sys.path.append(os.path.join(DOCS_DIR, os.pardir))
sys.path.insert(0, os.path.join(DOCS_DIR, os.pardir, os.pardir))

extensions = ['gunicorn_ext']
templates_path = ['_templates']
source_suffix = '.rst'
master_doc = 'index'

# General information about the project.
project = u'Gunicorn'
copyright = u'2009-%s, Benoit Chesneau' % time.strftime('%Y')
# gunicorn version
import gunicorn
release = version = gunicorn.__version__

exclude_patterns = []
pygments_style = 'sphinx'


# -- Options for HTML output ---------------------------------------------------

if not on_rtd:  # only import and set the theme if we're building docs locally
    try:
        import sphinx_rtd_theme
    except ImportError:
        html_theme = 'default'
    else:
        html_theme = 'sphinx_rtd_theme'
        html_theme_path = [sphinx_rtd_theme.get_html_theme_path()]
else:
    html_theme = 'default'

html_static_path = ['_static']
htmlhelp_basename = 'Gunicorndoc'


# -- Options for LaTeX output --------------------------------------------------

latex_elements = {

}

latex_documents = [
  ('index', 'Gunicorn.tex', u'Gunicorn Documentation',
   u'Benoit Chesneau', 'manual'),
]


# -- Options for manual page output --------------------------------------------
man_pages = [
    ('index', 'gunicorn', u'Gunicorn Documentation',
     [u'Benoit Chesneau'], 1)
]

texinfo_documents = [
  ('index', 'Gunicorn', u'Gunicorn Documentation',
   u'Benoit Chesneau', 'Gunicorn', 'One line description of project.',
   'Miscellaneous'),
]
