#!/usr/bin/env python
#
# Copyright (c) 2004, 2005 Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# * Redistributions of source code must retain the above copyright
#   notice, this list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in
#   the documentation and/or other materials provided with the
#   distribution.
#
# * Neither the name of Google nor the names of its contributors may
#   be used to endorse or promote products derived from this software
#   without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
#
# The sitemap_gen.py script is written in Python 2.2 and released to
# the open source community for continuous improvements under the BSD
# 2.0 new license, which can be found at:
#
#   http://www.opensource.org/licenses/bsd-license.php
#

__usage__ = \
"""A simple script to automatically produce sitemaps for a webserver,
in the Google Sitemap Protocol (GSP).

Usage: python sitemap_gen.py --config=config.xml [--help] [--testing]
            --config=config.xml, specifies config file location
            --help, displays usage message
            --testing, specified when user is experimenting
"""

# Please be careful that all syntax used in this file can be parsed on
# Python 1.5 -- this version check is not evaluated until after the
# entire file has been parsed.
import sys
if sys.hexversion < 0x02020000:
  print 'This script requires Python 2.2 or later.'
  print 'Currently run with version: %s' % sys.version
  sys.exit(1)

import fnmatch
import glob
import gzip
import hashlib
import os
import re
import stat
import time
import types
import urllib
import urlparse
import xml.sax

# True and False were introduced in Python2.2.2
try:
  testTrue=True
  del testTrue
except NameError:
  True=1
  False=0

# Text encodings
ENC_ASCII = 'ASCII'
ENC_UTF8  = 'UTF-8'
ENC_IDNA  = 'IDNA'
ENC_ASCII_LIST = ['ASCII', 'US-ASCII', 'US', 'IBM367', 'CP367', 'ISO646-US'
                  'ISO_646.IRV:1991', 'ISO-IR-6', 'ANSI_X3.4-1968',
                  'ANSI_X3.4-1986', 'CPASCII' ]
ENC_DEFAULT_LIST = ['ISO-8859-1', 'ISO-8859-2', 'ISO-8859-5']

# Maximum number of urls in each sitemap, before next Sitemap is created
MAXURLS_PER_SITEMAP = 50000

# Suffix on a Sitemap index file
SITEINDEX_SUFFIX = '_index.xml'

# Regular expressions tried for extracting URLs from access logs.
ACCESSLOG_CLF_PATTERN = re.compile(
  r'.+\s+"([^\s]+)\s+([^\s]+)\s+HTTP/\d+\.\d+"\s+200\s+.*'
  )

# Match patterns for lastmod attributes
LASTMOD_PATTERNS = map(re.compile, [
  r'^\d\d\d\d$',
  r'^\d\d\d\d-\d\d$',
  r'^\d\d\d\d-\d\d-\d\d$',
  r'^\d\d\d\d-\d\d-\d\dT\d\d:\d\dZ$',
  r'^\d\d\d\d-\d\d-\d\dT\d\d:\d\d[+-]\d\d:\d\d$',
  r'^\d\d\d\d-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$',
  r'^\d\d\d\d-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?[+-]\d\d:\d\d$',
  ])

# Match patterns for changefreq attributes
CHANGEFREQ_PATTERNS = [
  'always', 'hourly', 'daily', 'weekly', 'monthly', 'yearly', 'never'
  ]

# XML formats
SITEINDEX_HEADER   = \
  '<?xml version="1.0" encoding="UTF-8"?>\n' \
  '<sitemapindex\n' \
  '  xmlns="http://www.google.com/schemas/sitemap/0.84"\n' \
  '  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n' \
  '  xsi:schemaLocation="http://www.google.com/schemas/sitemap/0.84\n' \
  '                      http://www.google.com/schemas/sitemap/0.84/' \
  'siteindex.xsd">\n'
SITEINDEX_FOOTER   = '</sitemapindex>\n'
SITEINDEX_ENTRY    = \
  ' <sitemap>\n' \
  '  <loc>%(loc)s</loc>\n' \
  '  <lastmod>%(lastmod)s</lastmod>\n' \
  ' </sitemap>\n'
SITEMAP_HEADER     = \
  '<?xml version="1.0" encoding="UTF-8"?>\n' \
  '<urlset\n' \
  '  xmlns="http://www.google.com/schemas/sitemap/0.84"\n' \
  '  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n' \
  '  xsi:schemaLocation="http://www.google.com/schemas/sitemap/0.84\n' \
  '                      http://www.google.com/schemas/sitemap/0.84/' \
  'sitemap.xsd">\n'
SITEMAP_FOOTER     = '</urlset>\n'
SITEURL_XML_PREFIX = ' <url>\n'
SITEURL_XML_SUFFIX = ' </url>\n'

# Search engines to notify with the updated sitemaps
#
# This list is very non-obvious in what's going on.  Here's the gist:
# Each item in the list is a 6-tuple of items.  The first 5 are "almost"
# the same as the input arguments to urlparse.urlunsplit():
#   0 - schema
#   1 - netloc
#   2 - path
#   3 - query    <-- EXCEPTION: specify a query map rather than a string
#   4 - fragment
# Additionally, add item 5:
#   5 - query attribute that should be set to the new Sitemap URL
# Clear as mud, I know.
NOTIFICATION_SITES = [
  ('http', 'www.google.com', 'webmasters/sitemaps/ping', {}, '', 'sitemap')
  ]


class Error(Exception):
  """
  Base exception class.  In this module we tend not to use our own exception
  types for very much, but they come in very handy on XML parsing with SAX.
  """
  pass
#end class Error


class SchemaError(Error):
  """Failure to process an XML file according to the schema we know."""
  pass
#end class SchemeError


class Encoder:
  """
  Manages wide-character/narrow-character conversions for just about all
  text that flows into or out of the script.

  You should always use this class for string coercion, as opposed to
  letting Python handle coercions automatically.  Reason: Python
  usually assumes ASCII (7-bit) as a default narrow character encoding,
  which is not the kind of data we generally deal with.

  General high-level methodologies used in sitemap_gen:

  [PATHS]
  File system paths may be wide or narrow, depending on platform.
  This works fine, just be aware of it and be very careful to not
  mix them.  That is, if you have to pass several file path arguments
  into a library call, make sure they are all narrow or all wide.
  This class has MaybeNarrowPath() which should be called on every
  file system path you deal with.

  [URLS]
  URL locations are stored in Narrow form, already escaped.  This has the
  benefit of keeping escaping and encoding as close as possible to the format
  we read them in.  The downside is we may end up with URLs that have
  intermingled encodings -- the root path may be encoded in one way
  while the filename is encoded in another.  This is obviously wrong, but
  it should hopefully be an issue hit by very few users.  The workaround
  from the user level (assuming they notice) is to specify a default_encoding
  parameter in their config file.

  [OTHER]
  Other text, such as attributes of the URL class, configuration options,
  etc, are generally stored in Unicode for simplicity.
  """

  def __init__(self):
    self._user      = None                  # User-specified default encoding
    self._learned   = []                    # Learned default encodings
    self._widefiles = False                 # File system can be wide

    # Can the file system be Unicode?
    try:
      self._widefiles = os.path.supports_unicode_filenames
    except AttributeError:
      try:
        self._widefiles = sys.getwindowsversion() == os.VER_PLATFORM_WIN32_NT
      except AttributeError:
        pass

    # Try to guess a working default
    try:
      encoding = sys.getfilesystemencoding()
      if encoding and not (encoding.upper() in ENC_ASCII_LIST):
        self._learned = [ encoding ]
    except AttributeError:
      pass

    if not self._learned:
      encoding = sys.getdefaultencoding()
      if encoding and not (encoding.upper() in ENC_ASCII_LIST):
        self._learned = [ encoding ]

    # If we had no guesses, start with some European defaults
    if not self._learned:
      self._learned = ENC_DEFAULT_LIST
  #end def __init__

  def SetUserEncoding(self, encoding):
    self._user = encoding
  #end def SetUserEncoding

  def NarrowText(self, text, encoding):
    """ Narrow a piece of arbitrary text """
    if type(text) != types.UnicodeType:
      return text

    # Try the passed in preference
    if encoding:
      try:
        result = text.encode(encoding)
        if not encoding in self._learned:
          self._learned.append(encoding)
        return result
      except UnicodeError:
        pass
      except LookupError:
        output.Warn('Unknown encoding: %s' % encoding)

    # Try the user preference
    if self._user:
      try:
        return text.encode(self._user)
      except UnicodeError:
        pass
      except LookupError:
        temp = self._user
        self._user = None
        output.Warn('Unknown default_encoding: %s' % temp)

    # Look through learned defaults, knock any failing ones out of the list
    while self._learned:
      try:
        return text.encode(self._learned[0])
      except:
        del self._learned[0]

    # When all other defaults are exhausted, use UTF-8
    try:
      return text.encode(ENC_UTF8)
    except UnicodeError:
      pass

    # Something is seriously wrong if we get to here
    return text.encode(ENC_ASCII, 'ignore')
  #end def NarrowText

  def MaybeNarrowPath(self, text):
    """ Paths may be allowed to stay wide """
    if self._widefiles:
      return text
    return self.NarrowText(text, None)
  #end def MaybeNarrowPath

  def WidenText(self, text, encoding):
    """ Widen a piece of arbitrary text """
    if type(text) != types.StringType:
      return text

    # Try the passed in preference
    if encoding:
      try:
        result = unicode(text, encoding)
        if not encoding in self._learned:
          self._learned.append(encoding)
        return result
      except UnicodeError:
        pass
      except LookupError:
        output.Warn('Unknown encoding: %s' % encoding)

    # Try the user preference
    if self._user:
      try:
        return unicode(text, self._user)
      except UnicodeError:
        pass
      except LookupError:
        temp = self._user
        self._user = None
        output.Warn('Unknown default_encoding: %s' % temp)

    # Look through learned defaults, knock any failing ones out of the list
    while self._learned:
      try:
        return unicode(text, self._learned[0])
      except:
        del self._learned[0]

    # When all other defaults are exhausted, use UTF-8
    try:
      return unicode(text, ENC_UTF8)
    except UnicodeError:
      pass

    # Getting here means it wasn't UTF-8 and we had no working default.
    # We really don't have anything "right" we can do anymore.
    output.Warn('Unrecognized encoding in text: %s' % text)
    if not self._user:
      output.Warn('You may need to set a default_encoding in your '
                  'configuration file.')
    return text.decode(ENC_ASCII, 'ignore')
  #end def WidenText
#end class Encoder
encoder = Encoder()


class Output:
  """
  Exposes logging functionality, and tracks how many errors
  we have thus output.

  Logging levels should be used as thus:
    Fatal     -- extremely sparingly
    Error     -- config errors, entire blocks of user 'intention' lost
    Warn      -- individual URLs lost
    Log(,0)   -- Un-suppressable text that's not an error
    Log(,1)   -- touched files, major actions
    Log(,2)   -- parsing notes, filtered or duplicated URLs
    Log(,3)   -- each accepted URL
  """

  def __init__(self):
    self.num_errors    = 0                   # Count of errors
    self.num_warns     = 0                   # Count of warnings

    self._errors_shown = {}                  # Shown errors
    self._warns_shown  = {}                  # Shown warnings
    self._verbose      = 0                   # Level of verbosity
  #end def __init__

  def Log(self, text, level):
    """ Output a blurb of diagnostic text, if the verbose level allows it """
    if text:
      text = encoder.NarrowText(text, None)
      if self._verbose >= level:
        print text
  #end def Log

  def Warn(self, text):
    """ Output and count a warning.  Suppress duplicate warnings. """
    if text:
      text = encoder.NarrowText(text, None)
      hash = hashlib.md5(text).hexdigest()
      if not self._warns_shown.has_key(hash):
        self._warns_shown[hash] = 1
        print '[WARNING] ' + text
      else:
        self.Log('(suppressed) [WARNING] ' + text, 3)
      self.num_warns = self.num_warns + 1
  #end def Warn

  def Error(self, text):
    """ Output and count an error.  Suppress duplicate errors. """
    if text:
      text = encoder.NarrowText(text, None)
      hash = hashlib.md5(text).hexdigest()
      if not self._errors_shown.has_key(hash):
        self._errors_shown[hash] = 1
        print '[ERROR] ' + text
      else:
        self.Log('(suppressed) [ERROR] ' + text, 3)
      self.num_errors = self.num_errors + 1
  #end def Error

  def Fatal(self, text):
    """ Output an error and terminate the program. """
    if text:
      text = encoder.NarrowText(text, None)
      print '[FATAL] ' + text
    else:
      print 'Fatal error.'
    sys.exit(1)
  #end def Fatal

  def SetVerbose(self, level):
    """ Sets the verbose level. """
    try:
      if type(level) != types.IntType:
        level = int(level)
      if (level >= 0) and (level <= 3):
        self._verbose = level
        return
    except ValueError:
      pass
    self.Error('Verbose level (%s) must be between 0 and 3 inclusive.' % level)
  #end def SetVerbose
#end class Output
output = Output()


class URL(object):
  """ URL is a smart structure grouping together the properties we
  care about for a single web reference. """
  __slots__ = 'loc', 'lastmod', 'changefreq', 'priority'

  def __init__(self):
    self.loc        = None                  # URL -- in Narrow characters
    self.lastmod    = None                  # ISO8601 timestamp of last modify
    self.changefreq = None                  # Text term for update frequency
    self.priority   = None                  # Float between 0 and 1 (inc)
  #end def __init__

  def __cmp__(self, other):
    if self.loc < other.loc:
      return -1
    if self.loc > other.loc:
      return 1
    return 0
  #end def __cmp__

  def TrySetAttribute(self, attribute, value):
    """ Attempt to set the attribute to the value, with a pretty try
    block around it.  """
    if attribute == 'loc':
      self.loc = self.Canonicalize(value)
    else:
      try:
        setattr(self, attribute, value)
      except AttributeError:
        output.Warn('Unknown URL attribute: %s' % attribute)
  #end def TrySetAttribute

  def IsAbsolute(loc):
    """ Decide if the URL is absolute or not """
    if not loc:
      return False
    narrow = encoder.NarrowText(loc, None)
    (scheme, netloc, path, query, frag) = urlparse.urlsplit(narrow)
    if (not scheme) or (not netloc):
      return False
    return True
  #end def IsAbsolute
  IsAbsolute = staticmethod(IsAbsolute)

  def Canonicalize(loc):
    """ Do encoding and canonicalization on a URL string """
    if not loc:
      return loc

    # Let the encoder try to narrow it
    narrow = encoder.NarrowText(loc, None)

    # Escape components individually
    (scheme, netloc, path, query, frag) = urlparse.urlsplit(narrow)
    unr    = '-._~'
    sub    = '!$&\'()*+,;='
    netloc = urllib.quote(netloc, unr + sub + '%:@/[]')
    path   = urllib.quote(path,   unr + sub + '%:@/')
    query  = urllib.quote(query,  unr + sub + '%:@/?')
    frag   = urllib.quote(frag,   unr + sub + '%:@/?')

    # Try built-in IDNA encoding on the netloc
    try:
      (ignore, widenetloc, ignore, ignore, ignore) = urlparse.urlsplit(loc)
      for c in widenetloc:
        if c >= unichr(128):
          netloc = widenetloc.encode(ENC_IDNA)
          netloc = urllib.quote(netloc, unr + sub + '%:@/[]')
          break
    except UnicodeError:
      # urlsplit must have failed, based on implementation differences in the
      # library.  There is not much we can do here, except ignore it.
      pass
    except LookupError:
      output.Warn('An International Domain Name (IDN) is being used, but this '
                  'version of Python does not have support for IDNA encoding. '
                  ' (IDNA support was introduced in Python 2.3)  The encoding '
                  'we have used instead is wrong and will probably not yield '
                  'valid URLs.')
    bad_netloc = False
    if '%' in netloc:
      bad_netloc = True

    # Put it all back together
    narrow = urlparse.urlunsplit((scheme, netloc, path, query, frag))

    # I let '%' through.  Fix any that aren't pre-existing escapes.
    HEXDIG = '0123456789abcdefABCDEF'
    list   = narrow.split('%')
    narrow = list[0]
    del list[0]
    for item in list:
      if (len(item) >= 2) and (item[0] in HEXDIG) and (item[1] in HEXDIG):
        narrow = narrow + '%' + item
      else:
        narrow = narrow + '%25' + item

    # Issue a warning if this is a bad URL
    if bad_netloc:
      output.Warn('Invalid characters in the host or domain portion of a URL: '
                  + narrow)

    return narrow
  #end def Canonicalize
  Canonicalize = staticmethod(Canonicalize)

  def Validate(self, base_url, allow_fragment):
    """ Verify the data in this URL is well-formed, and override if not. """
    assert type(base_url) == types.StringType

    # Test (and normalize) the ref
    if not self.loc:
      output.Warn('Empty URL')
      return False
    if allow_fragment:
      self.loc = urlparse.urljoin(base_url, self.loc)
    if not self.loc.startswith(base_url):
      output.Warn('Discarded URL for not starting with the base_url: %s' %
                  self.loc)
      self.loc = None
      return False

    # Test the lastmod
    if self.lastmod:
      match = False
      self.lastmod = self.lastmod.upper()
      for pattern in LASTMOD_PATTERNS:
        match = pattern.match(self.lastmod)
        if match:
          break
      if not match:
        output.Warn('Lastmod "%s" does not appear to be in ISO8601 format on '
                    'URL: %s' % (self.lastmod, self.loc))
        self.lastmod = None

    # Test the changefreq
    if self.changefreq:
      match = False
      self.changefreq = self.changefreq.lower()
      for pattern in CHANGEFREQ_PATTERNS:
        if self.changefreq == pattern:
          match = True
          break
      if not match:
        output.Warn('Changefreq "%s" is not a valid change frequency on URL '
                    ': %s' % (self.changefreq, self.loc))
        self.changefreq = None

    # Test the priority
    if self.priority:
      priority = -1.0
      try:
        priority = float(self.priority)
      except ValueError:
        pass
      if (priority < 0.0) or (priority > 1.0):
        output.Warn('Priority "%s" is not a number between 0 and 1 inclusive '
                    'on URL: %s' % (self.priority, self.loc))
        self.priority = None

    return True
  #end def Validate

  def MakeHash(self):
    """ Provides a uniform way of hashing URLs """
    if not self.loc:
      return None
    if self.loc.endswith('/'):
      return hashlib.md5(self.loc[:-1]).hexdigest()
    return hashlib.md5(self.loc).hexdigest()
  #end def MakeHash

  def Log(self, prefix='URL', level=3):
    """ Dump the contents, empty or not, to the log. """
    out = prefix + ':'

    for attribute in self.__slots__:
      value = getattr(self, attribute)
      if not value:
        value = ''
      out = out + ('  %s=[%s]' % (attribute, value))

    output.Log('%s' % encoder.NarrowText(out, None), level)
  #end def Log

  def WriteXML(self, file):
    """ Dump non-empty contents to the output file, in XML format. """
    if not self.loc:
      return
    out = SITEURL_XML_PREFIX

    for attribute in self.__slots__:
      value = getattr(self, attribute)
      if value:
        if type(value) == types.UnicodeType:
          value = encoder.NarrowText(value, None)
        elif type(value) != types.StringType:
          value = str(value)
        value = xml.sax.saxutils.escape(value)
        out = out + ('  <%s>%s</%s>\n' % (attribute, value, attribute))

    out = out + SITEURL_XML_SUFFIX
    file.write(out)
  #end def WriteXML
#end class URL


class Filter:
  """
  A filter on the stream of URLs we find.  A filter is, in essence,
  a wildcard applied to the stream.  You can think of this as an
  operator that returns a tri-state when given a URL:

    True  -- this URL is to be included in the sitemap
    None  -- this URL is undecided
    False -- this URL is to be dropped from the sitemap
  """

  def __init__(self, attributes):
    self._wildcard  = None                  # Pattern for wildcard match
    self._regexp    = None                  # Pattern for regexp match
    self._pass      = False                 # "Drop" filter vs. "Pass" filter

    if not ValidateAttributes('FILTER', attributes,
                              ('pattern', 'type', 'action')):
      return

    # Check error count on the way in
    num_errors = output.num_errors

    # Fetch the attributes
    pattern = attributes.get('pattern')
    type    = attributes.get('type', 'wildcard')
    action  = attributes.get('action', 'drop')
    if type:
      type = type.lower()
    if action:
      action = action.lower()

    # Verify the attributes
    if not pattern:
      output.Error('On a filter you must specify a "pattern" to match')
    elif (not type) or ((type != 'wildcard') and (type != 'regexp')):
      output.Error('On a filter you must specify either \'type="wildcard"\' '
                   'or \'type="regexp"\'')
    elif (action != 'pass') and (action != 'drop'):
      output.Error('If you specify a filter action, it must be either '
                   '\'action="pass"\' or \'action="drop"\'')

    # Set the rule
    if action == 'drop':
      self._pass = False
    elif action == 'pass':
      self._pass = True

    if type == 'wildcard':
      self._wildcard = pattern
    elif type == 'regexp':
      try:
        self._regexp = re.compile(pattern)
      except re.error:
        output.Error('Bad regular expression: %s' %  pattern)

    # Log the final results iff we didn't add any errors
    if num_errors == output.num_errors:
      output.Log('Filter: %s any URL that matches %s "%s"' %
                 (action, type, pattern), 2)
  #end def __init__

  def Apply(self, url):
    """ Process the URL, as above. """
    if (not url) or (not url.loc):
      return None

    if self._wildcard:
      if fnmatch.fnmatchcase(url.loc, self._wildcard):
        return self._pass
      return None

    if self._regexp:
      if self._regexp.search(url.loc):
        return self._pass
      return None

    assert False # unreachable
  #end def Apply
#end class Filter


class InputURL:
  """
  Each Input class knows how to yield a set of URLs from a data source.

  This one handles a single URL, manually specified in the config file.
  """

  def __init__(self, attributes):
    self._url = None                        # The lonely URL

    if not ValidateAttributes('URL', attributes,
                                ('href', 'lastmod', 'changefreq', 'priority')):
      return

    url = URL()
    for attr in attributes.keys():
      if attr == 'href':
        url.TrySetAttribute('loc', attributes[attr])
      else:
        url.TrySetAttribute(attr, attributes[attr])

    if not url.loc:
      output.Error('Url entries must have an href attribute.')
      return

    self._url = url
    output.Log('Input: From URL "%s"' % self._url.loc, 2)
  #end def __init__

  def ProduceURLs(self, consumer):
    """ Produces URLs from our data source, hands them in to the consumer. """
    if self._url:
      consumer(self._url, True)
  #end def ProduceURLs
#end class InputURL


class InputURLList:
  """
  Each Input class knows how to yield a set of URLs from a data source.

  This one handles a text file with a list of URLs
  """

  def __init__(self, attributes):
    self._path      = None                  # The file path
    self._encoding  = None                  # Encoding of that file

    if not ValidateAttributes('URLLIST', attributes, ('path', 'encoding')):
      return

    self._path      = attributes.get('path')
    self._encoding  = attributes.get('encoding', ENC_UTF8)
    if self._path:
      self._path    = encoder.MaybeNarrowPath(self._path)
      if os.path.isfile(self._path):
        output.Log('Input: From URLLIST "%s"' % self._path, 2)
      else:
        output.Error('Can not locate file: %s' % self._path)
        self._path = None
    else:
      output.Error('Urllist entries must have a "path" attribute.')
  #end def __init__

  def ProduceURLs(self, consumer):
    """ Produces URLs from our data source, hands them in to the consumer. """

    # Open the file
    (frame, file) = OpenFileForRead(self._path, 'URLLIST')
    if not file:
      return

    # Iterate lines
    linenum = 0
    for line in file.readlines():
      linenum = linenum + 1

      # Strip comments and empty lines
      if self._encoding:
        line = encoder.WidenText(line, self._encoding)
      line = line.strip()
      if (not line) or line[0] == '#':
        continue

      # Split the line on space
      url = URL()
      cols = line.split(' ')
      for i in range(0,len(cols)):
        cols[i] = cols[i].strip()
      url.TrySetAttribute('loc', cols[0])

      # Extract attributes from the other columns
      for i in range(1,len(cols)):
        if cols[i]:
          try:
            (attr_name, attr_val) = cols[i].split('=', 1)
            url.TrySetAttribute(attr_name, attr_val)
          except ValueError:
            output.Warn('Line %d: Unable to parse attribute: %s' %
                        (linenum, cols[i]))

      # Pass it on
      consumer(url, False)

    file.close()
    if frame:
      frame.close()
  #end def ProduceURLs
#end class InputURLList


class InputDirectory:
  """
  Each Input class knows how to yield a set of URLs from a data source.

  This one handles a directory that acts as base for walking the filesystem.
  """

  def __init__(self, attributes, base_url):
    self._path         = None               # The directory
    self._url          = None               # The URL equivelant
    self._default_file = None

    if not ValidateAttributes('DIRECTORY', attributes, ('path', 'url',
                                                           'default_file')):
      return

    # Prep the path -- it MUST end in a sep
    path = attributes.get('path')
    if not path:
      output.Error('Directory entries must have both "path" and "url" '
                  'attributes')
      return
    path = encoder.MaybeNarrowPath(path)
    if not path.endswith(os.sep):
      path = path + os.sep
    if not os.path.isdir(path):
      output.Error('Can not locate directory: %s' % path)
      return

    # Prep the URL -- it MUST end in a sep
    url = attributes.get('url')
    if not url:
      output.Error('Directory entries must have both "path" and "url" '
                  'attributes')
      return
    url = URL.Canonicalize(url)
    if not url.endswith('/'):
      url = url + '/'
    if not url.startswith(base_url):
      url = urlparse.urljoin(base_url, url)
      if not url.startswith(base_url):
        output.Error('The directory URL "%s" is not relative to the '
                    'base_url: %s' % (url, base_url))
        return

    # Prep the default file -- it MUST be just a filename
    file = attributes.get('default_file')
    if file:
      file = encoder.MaybeNarrowPath(file)
      if os.sep in file:
        output.Error('The default_file "%s" can not include path information.'
                     % file)
        file = None

    self._path         = path
    self._url          = url
    self._default_file = file
    if file:
      output.Log('Input: From DIRECTORY "%s" (%s) with default file "%s"'
                 % (path, url, file), 2)
    else:
      output.Log('Input: From DIRECTORY "%s" (%s) with no default file'
                 % (path, url), 2)
  #end def __init__

  def ProduceURLs(self, consumer):
    """ Produces URLs from our data source, hands them in to the consumer. """
    if not self._path:
      return

    root_path = self._path
    root_URL  = self._url
    root_file = self._default_file

    def PerFile(dirpath, name):
      """
      Called once per file.
      Note that 'name' will occasionally be None -- for a directory itself
      """
      # Pull a timestamp
      url           = URL()
      isdir         = False
      try:
        if name:
          path      = os.path.join(dirpath, name)
        else:
          path      = dirpath
        isdir       = os.path.isdir(path)
        time        = None
        if isdir and root_file:
          file      = os.path.join(path, root_file)
          try:
            time    = os.stat(file)[stat.ST_MTIME];
          except OSError:
            pass
        if not time:
          time      = os.stat(path)[stat.ST_MTIME];
        url.lastmod = TimestampISO8601(time)
      except OSError:
        pass
      except ValueError:
        pass

      # Build a URL
      middle        = dirpath[len(root_path):]
      if os.sep != '/':
        middle = middle.replace(os.sep, '/')
      if middle:
        middle      = middle + '/'
      if name:
        middle      = middle + name
        if isdir:
          middle    = middle + '/'
      url.TrySetAttribute('loc', root_URL + encoder.WidenText(middle, None))

      # Suppress default files.  (All the way down here so we can log it.)
      if name and (root_file == name):
        url.Log(prefix='IGNORED (default file)', level=2)
        return

      consumer(url, False)
    #end def PerFile

    def PerDirectory(ignore, dirpath, namelist):
      """
      Called once per directory with a list of all the contained files/dirs.
      """
      ignore = ignore  # Avoid warnings of an unused parameter

      if not dirpath.startswith(root_path):
        output.Warn('Unable to decide what the root path is for directory: '
                    '%s' % dirpath)
        return

      for name in namelist:
        PerFile(dirpath, name)
    #end def PerDirectory

    output.Log('Walking DIRECTORY "%s"' % self._path, 1)
    PerFile(self._path, None)
    os.path.walk(self._path, PerDirectory, None)
  #end def ProduceURLs
#end class InputDirectory


class InputAccessLog:
  """
  Each Input class knows how to yield a set of URLs from a data source.

  This one handles access logs.  It's non-trivial in that we want to
  auto-detect log files in the Common Logfile Format (as used by Apache,
  for instance) and the Extended Log File Format (as used by IIS, for
  instance).
  """

  def __init__(self, attributes):
    self._path         = None               # The file path
    self._encoding     = None               # Encoding of that file
    self._is_elf       = False              # Extended Log File Format?
    self._is_clf       = False              # Common Logfile Format?
    self._elf_status   = -1                 # ELF field: '200'
    self._elf_method   = -1                 # ELF field: 'HEAD'
    self._elf_uri      = -1                 # ELF field: '/foo?bar=1'
    self._elf_urifrag1 = -1                 # ELF field: '/foo'
    self._elf_urifrag2 = -1                 # ELF field: 'bar=1'

    if not ValidateAttributes('ACCESSLOG', attributes, ('path', 'encoding')):
      return

    self._path      = attributes.get('path')
    self._encoding  = attributes.get('encoding', ENC_UTF8)
    if self._path:
      self._path    = encoder.MaybeNarrowPath(self._path)
      if os.path.isfile(self._path):
        output.Log('Input: From ACCESSLOG "%s"' % self._path, 2)
      else:
        output.Error('Can not locate file: %s' % self._path)
        self._path = None
    else:
      output.Error('Accesslog entries must have a "path" attribute.')
  #end def __init__

  def RecognizeELFLine(self, line):
    """ Recognize the Fields directive that heads an ELF file """
    if not line.startswith('#Fields:'):
      return False
    fields = line.split(' ')
    del fields[0]
    for i in range(0, len(fields)):
      field = fields[i].strip()
      if field == 'sc-status':
        self._elf_status   = i
      elif field == 'cs-method':
        self._elf_method   = i
      elif field == 'cs-uri':
        self._elf_uri      = i
      elif field == 'cs-uri-stem':
        self._elf_urifrag1 = i
      elif field == 'cs-uri-query':
        self._elf_urifrag2 = i
    output.Log('Recognized an Extended Log File Format file.', 2)
    return True
  #end def RecognizeELFLine

  def GetELFLine(self, line):
    """ Fetch the requested URL from an ELF line """
    fields = line.split(' ')
    count  = len(fields)

    # Verify status was Ok
    if self._elf_status >= 0:
      if self._elf_status >= count:
        return None
      if not fields[self._elf_status].strip() == '200':
        return None

    # Verify method was HEAD or GET
    if self._elf_method >= 0:
      if self._elf_method >= count:
        return None
      if not fields[self._elf_method].strip() in ('HEAD', 'GET'):
        return None

    # Pull the full URL if we can
    if self._elf_uri >= 0:
      if self._elf_uri >= count:
        return None
      url = fields[self._elf_uri].strip()
      if url != '-':
        return url

    # Put together a fragmentary URL
    if self._elf_urifrag1 >= 0:
      if self._elf_urifrag1 >= count or self._elf_urifrag2 >= count:
        return None
      urlfrag1 = fields[self._elf_urifrag1].strip()
      urlfrag2 = None
      if self._elf_urifrag2 >= 0:
        urlfrag2 = fields[self._elf_urifrag2]
      if urlfrag1 and (urlfrag1 != '-'):
        if urlfrag2 and (urlfrag2 != '-'):
          urlfrag1 = urlfrag1 + '?' + urlfrag2
        return urlfrag1

    return None
  #end def GetELFLine

  def RecognizeCLFLine(self, line):
    """ Try to tokenize a logfile line according to CLF pattern and see if
    it works. """
    match = ACCESSLOG_CLF_PATTERN.match(line)
    recognize = match and (match.group(1) in ('HEAD', 'GET'))
    if recognize:
      output.Log('Recognized a Common Logfile Format file.', 2)
    return recognize
  #end def RecognizeCLFLine

  def GetCLFLine(self, line):
    """ Fetch the requested URL from a CLF line """
    match = ACCESSLOG_CLF_PATTERN.match(line)
    if match:
      request = match.group(1)
      if request in ('HEAD', 'GET'):
        return match.group(2)
    return None
  #end def GetCLFLine

  def ProduceURLs(self, consumer):
    """ Produces URLs from our data source, hands them in to the consumer. """

    # Open the file
    (frame, file) = OpenFileForRead(self._path, 'ACCESSLOG')
    if not file:
      return

    # Iterate lines
    for line in file.readlines():
      if self._encoding:
        line = encoder.WidenText(line, self._encoding)
      line = line.strip()

      # If we don't know the format yet, try them both
      if (not self._is_clf) and (not self._is_elf):
        self._is_elf = self.RecognizeELFLine(line)
        self._is_clf = self.RecognizeCLFLine(line)

      # Digest the line
      match = None
      if self._is_elf:
        match = self.GetELFLine(line)
      elif self._is_clf:
        match = self.GetCLFLine(line)
      if not match:
        continue

      # Pass it on
      url = URL()
      url.TrySetAttribute('loc', match)
      consumer(url, True)

    file.close()
    if frame:
      frame.close()
  #end def ProduceURLs
#end class InputAccessLog


class InputSitemap(xml.sax.handler.ContentHandler):

  """
  Each Input class knows how to yield a set of URLs from a data source.

  This one handles Sitemap files and Sitemap index files.  For the sake
  of simplicity in design (and simplicity in interfacing with the SAX
  package), we do not handle these at the same time, recursively.  Instead
  we read an index file completely and make a list of Sitemap files, then
  go back and process each Sitemap.
  """

  class _ContextBase(object):

    """Base class for context handlers in our SAX processing.  A context
    handler is a class that is responsible for understanding one level of
    depth in the XML schema.  The class knows what sub-tags are allowed,
    and doing any processing specific for the tag we're in.

    This base class is the API filled in by specific context handlers,
    all defined below.
    """

    def __init__(self, subtags):
      """Initialize with a sequence of the sub-tags that would be valid in
      this context."""
      self._allowed_tags = subtags          # Sequence of sub-tags we can have
      self._last_tag     = None             # Most recent seen sub-tag
    #end def __init__

    def AcceptTag(self, tag):
      """Returns True iff opening a sub-tag is valid in this context."""
      valid = tag in self._allowed_tags
      if valid:
        self._last_tag = tag
      else:
        self._last_tag = None
      return valid
    #end def AcceptTag

    def AcceptText(self, text):
      """Returns True iff a blurb of text is valid in this context."""
      return False
    #end def AcceptText

    def Open(self):
      """The context is opening.  Do initialization."""
      pass
    #end def Open

    def Close(self):
      """The context is closing.  Return our result, if any."""
      pass
    #end def Close

    def Return(self, result):
      """We're returning to this context after handling a sub-tag.  This
      method is called with the result data from the sub-tag that just
      closed.  Here in _ContextBase, if we ever see a result it means
      the derived child class forgot to override this method."""
      if result:
        raise NotImplementedError
    #end def Return
  #end class _ContextBase

  class _ContextUrlSet(_ContextBase):

    """Context handler for the document node in a Sitemap."""

    def __init__(self):
      InputSitemap._ContextBase.__init__(self, ('url',))
    #end def __init__
  #end class _ContextUrlSet

  class _ContextUrl(_ContextBase):

    """Context handler for a URL node in a Sitemap."""

    def __init__(self, consumer):
      """Initialize this context handler with the callable consumer that
      wants our URLs."""
      InputSitemap._ContextBase.__init__(self, URL.__slots__)
      self._url          = None            # The URL object we're building
      self._consumer     = consumer        # Who wants to consume it
    #end def __init__

    def Open(self):
      """Initialize the URL."""
      assert not self._url
      self._url = URL()
    #end def Open

    def Close(self):
      """Pass the URL to the consumer and reset it to None."""
      assert self._url
      self._consumer(self._url, False)
      self._url = None
    #end def Close

    def Return(self, result):
      """A value context has closed, absorb the data it gave us."""
      assert self._url
      if result:
        self._url.TrySetAttribute(self._last_tag, result)
    #end def Return
  #end class _ContextUrl

  class _ContextSitemapIndex(_ContextBase):

    """Context handler for the document node in an index file."""

    def __init__(self):
      InputSitemap._ContextBase.__init__(self, ('sitemap',))
      self._loclist = []                    # List of accumulated Sitemap URLs
    #end def __init__

    def Open(self):
      """Just a quick verify of state."""
      assert not self._loclist
    #end def Open

    def Close(self):
      """Return our list of accumulated URLs."""
      if self._loclist:
        temp = self._loclist
        self._loclist = []
        return temp
    #end def Close

    def Return(self, result):
      """Getting a new loc URL, add it to the collection."""
      if result:
        self._loclist.append(result)
    #end def Return
  #end class _ContextSitemapIndex

  class _ContextSitemap(_ContextBase):

    """Context handler for a Sitemap entry in an index file."""

    def __init__(self):
      InputSitemap._ContextBase.__init__(self, ('loc', 'lastmod'))
      self._loc = None                      # The URL to the Sitemap
    #end def __init__

    def Open(self):
      """Just a quick verify of state."""
      assert not self._loc
    #end def Open

    def Close(self):
      """Return our URL to our parent."""
      if self._loc:
        temp = self._loc
        self._loc = None
        return temp
      output.Warn('In the Sitemap index file, a "sitemap" entry had no "loc".')
    #end def Close

    def Return(self, result):
      """A value has closed.  If it was a 'loc', absorb it."""
      if result and (self._last_tag == 'loc'):
        self._loc = result
    #end def Return
  #end class _ContextSitemap

  class _ContextValue(_ContextBase):

    """Context handler for a single value.  We return just the value.  The
    higher level context has to remember what tag led into us."""

    def __init__(self):
      InputSitemap._ContextBase.__init__(self, ())
      self._text        = None
    #end def __init__

    def AcceptText(self, text):
      """Allow all text, adding it to our buffer."""
      if self._text:
        self._text = self._text + text
      else:
        self._text = text
      return True
    #end def AcceptText

    def Open(self):
      """Initialize our buffer."""
      self._text = None
    #end def Open

    def Close(self):
      """Return what's in our buffer."""
      text = self._text
      self._text = None
      if text:
        text = text.strip()
      return text
    #end def Close
  #end class _ContextValue

  def __init__(self, attributes):
    """Initialize with a dictionary of attributes from our entry in the
    config file."""
    xml.sax.handler.ContentHandler.__init__(self)
    self._pathlist      = None              # A list of files
    self._current       = -1                # Current context in _contexts
    self._contexts      = None              # The stack of contexts we allow
    self._contexts_idx  = None              # ...contexts for index files
    self._contexts_stm  = None              # ...contexts for Sitemap files

    if not ValidateAttributes('SITEMAP', attributes, ['path']):
      return

    # Init the first file path
    path = attributes.get('path')
    if path:
      path = encoder.MaybeNarrowPath(path)
      if os.path.isfile(path):
        output.Log('Input: From SITEMAP "%s"' % path, 2)
        self._pathlist = [path]
      else:
        output.Error('Can not locate file "%s"' % path)
    else:
      output.Error('Sitemap entries must have a "path" attribute.')
  #end def __init__

  def ProduceURLs(self, consumer):
    """In general: Produces URLs from our data source, hand them to the
    callable consumer.

    In specific: Iterate over our list of paths and delegate the actual
    processing to helper methods.  This is a complexity no other data source
    needs to suffer.  We are unique in that we can have files that tell us
    to bring in other files.

    Note the decision to allow an index file or not is made in this method.
    If we call our parser with (self._contexts == None) the parser will
    grab whichever context stack can handle the file.  IE: index is allowed.
    If instead we set (self._contexts = ...) before parsing, the parser
    will only use the stack we specify.  IE: index not allowed.
    """
    # Set up two stacks of contexts
    self._contexts_idx = [InputSitemap._ContextSitemapIndex(),
                          InputSitemap._ContextSitemap(),
                          InputSitemap._ContextValue()]

    self._contexts_stm = [InputSitemap._ContextUrlSet(),
                          InputSitemap._ContextUrl(consumer),
                          InputSitemap._ContextValue()]

    # Process the first file
    assert self._pathlist
    path = self._pathlist[0]
    self._contexts = None                # We allow an index file here
    self._ProcessFile(path)

    # Iterate over remaining files
    self._contexts = self._contexts_stm  # No index files allowed
    for path in self._pathlist[1:]:
      self._ProcessFile(path)
  #end def ProduceURLs

  def _ProcessFile(self, path):
    """Do per-file reading/parsing/consuming for the file path passed in."""
    assert path

    # Open our file
    (frame, file) = OpenFileForRead(path, 'SITEMAP')
    if not file:
      return

    # Rev up the SAX engine
    try:
      self._current = -1
      xml.sax.parse(file, self)
    except SchemaError:
      output.Error('An error in file "%s" made us abort reading the Sitemap.'
                   % path)
    except IOError:
      output.Error('Cannot read from file "%s"' % path)
    except xml.sax._exceptions.SAXParseException, e:
      output.Error('XML error in the file "%s" (line %d, column %d): %s' %
                   (path, e._linenum, e._colnum, e.getMessage()))

    # Clean up
    file.close()
    if frame:
      frame.close()
  #end def _ProcessFile

  def _MungeLocationListIntoFiles(self, urllist):
    """Given a list of URLs, munge them into our self._pathlist property.
    We do this by assuming all the files live in the same directory as
    the first file in the existing pathlist.  That is, we assume a
    Sitemap index points to Sitemaps only in the same directory.  This
    is not true in general, but will be true for any output produced
    by this script.
    """
    assert self._pathlist
    path = self._pathlist[0]
    path = os.path.normpath(path)
    dir  = os.path.dirname(path)
    wide = False
    if type(path) == types.UnicodeType:
      wide = True

    for url in urllist:
      url = URL.Canonicalize(url)
      output.Log('Index points to Sitemap file at: %s' % url, 2)
      (scheme, netloc, path, query, frag) = urlparse.urlsplit(url)
      file = os.path.basename(path)
      file = urllib.unquote(file)
      if wide:
        file = encoder.WidenText(file)
      if dir:
        file = dir + os.sep + file
      if file:
        self._pathlist.append(file)
        output.Log('Will attempt to read Sitemap file: %s' % file, 1)
  #end def _MungeLocationListIntoFiles

  def startElement(self, tag, attributes):
    """SAX processing, called per node in the config stream.
    As long as the new tag is legal in our current context, this
    becomes an Open call on one context deeper.
    """
    # If this is the document node, we may have to look for a context stack
    if (self._current < 0) and not self._contexts:
      assert self._contexts_idx and self._contexts_stm
      if tag == 'urlset':
        self._contexts = self._contexts_stm
      elif tag == 'sitemapindex':
        self._contexts = self._contexts_idx
        output.Log('File is a Sitemap index.', 2)
      else:
        output.Error('The document appears to be neither a Sitemap nor a '
                     'Sitemap index.')
        raise SchemaError

    # Display a kinder error on a common mistake
    if (self._current < 0) and (self._contexts == self._contexts_stm) and (
      tag == 'sitemapindex'):
      output.Error('A Sitemap index can not refer to another Sitemap index.')
      raise SchemaError

    # Verify no unexpected attributes
    if attributes:
      text = ''
      for attr in attributes.keys():
        # The document node will probably have namespaces
        if self._current < 0:
          if attr.find('xmlns') >= 0:
            continue
          if attr.find('xsi') >= 0:
            continue
        if text:
          text = text + ', '
        text = text + attr
      if text:
        output.Warn('Did not expect any attributes on any tag, instead tag '
                     '"%s" had attributes: %s' % (tag, text))

    # Switch contexts
    if (self._current < 0) or (self._contexts[self._current].AcceptTag(tag)):
      self._current = self._current + 1
      assert self._current < len(self._contexts)
      self._contexts[self._current].Open()
    else:
      output.Error('Can not accept tag "%s" where it appears.' % tag)
      raise SchemaError
  #end def startElement

  def endElement(self, tag):
    """SAX processing, called per node in the config stream.
    This becomes a call to Close on one context followed by a call
    to Return on the previous.
    """
    tag = tag  # Avoid warning on unused argument
    assert self._current >= 0
    retval = self._contexts[self._current].Close()
    self._current = self._current - 1
    if self._current >= 0:
      self._contexts[self._current].Return(retval)
    elif retval and (self._contexts == self._contexts_idx):
      self._MungeLocationListIntoFiles(retval)
  #end def endElement

  def characters(self, text):
    """SAX processing, called when text values are read.  Important to
    note that one single text value may be split across multiple calls
    of this method.
    """
    if (self._current < 0) or (
      not self._contexts[self._current].AcceptText(text)):
      if text.strip():
        output.Error('Can not accept text "%s" where it appears.' % text)
        raise SchemaError
  #end def characters
#end class InputSitemap


class FilePathGenerator:
  """
  This class generates filenames in a series, upon request.
  You can request any iteration number at any time, you don't
  have to go in order.

  Example of iterations for '/path/foo.xml.gz':
    0           --> /path/foo.xml.gz
    1           --> /path/foo1.xml.gz
    2           --> /path/foo2.xml.gz
    _index.xml  --> /path/foo_index.xml
  """

  def __init__(self):
    self.is_gzip     = False                 # Is this a  GZIP file?

    self._path       = None                  # '/path/'
    self._prefix     = None                  # 'foo'
    self._suffix     = None                  # '.xml.gz'
  #end def __init__

  def Preload(self, path):
    """ Splits up a path into forms ready for recombination. """
    path = encoder.MaybeNarrowPath(path)

    # Get down to a base name
    path = os.path.normpath(path)
    base = os.path.basename(path).lower()
    if not base:
      output.Error('Couldn\'t parse the file path: %s' % path)
      return False
    lenbase = len(base)

    # Recognize extension
    lensuffix = 0
    compare_suffix = ['.xml', '.xml.gz', '.gz']
    for suffix in compare_suffix:
      if base.endswith(suffix):
        lensuffix = len(suffix)
        break
    if not lensuffix:
      output.Error('The path "%s" doesn\'t end in a supported file '
                   'extension.' % path)
      return False
    self.is_gzip = suffix.endswith('.gz')

    # Split the original path
    lenpath = len(path)
    self._path   = path[:lenpath-lenbase]
    self._prefix = path[lenpath-lenbase:lenpath-lensuffix]
    self._suffix = path[lenpath-lensuffix:]

    return True
  #end def Preload

  def GeneratePath(self, instance):
    """ Generates the iterations, as described above. """
    prefix = self._path + self._prefix
    if type(instance) == types.IntType:
      if instance:
        return '%s%d%s' % (prefix, instance, self._suffix)
      return prefix + self._suffix
    return prefix + instance
  #end def GeneratePath

  def GenerateURL(self, instance, root_url):
    """ Generates iterations, but as a URL instead of a path. """
    prefix = root_url + self._prefix
    retval = None
    if type(instance) == types.IntType:
      if instance:
        retval = '%s%d%s' % (prefix, instance, self._suffix)
      else:
        retval = prefix + self._suffix
    else:
      retval = prefix + instance
    return URL.Canonicalize(retval)
  #end def GenerateURL

  def GenerateWildURL(self, root_url):
    """ Generates a wildcard that should match all our iterations """
    prefix = URL.Canonicalize(root_url + self._prefix)
    temp   = URL.Canonicalize(prefix + self._suffix)
    suffix = temp[len(prefix):]
    return prefix + '*' + suffix
  #end def GenerateURL
#end class FilePathGenerator


class PerURLStatistics:
  """ Keep track of some simple per-URL statistics, like file extension. """

  def __init__(self):
    self._extensions  = {}                  # Count of extension instances
  #end def __init__

  def Consume(self, url):
    """ Log some stats for the URL.  At the moment, that means extension. """
    if url and url.loc:
      (scheme, netloc, path, query, frag) = urlparse.urlsplit(url.loc)
      if not path:
        return

      # Recognize directories
      if path.endswith('/'):
        if self._extensions.has_key('/'):
          self._extensions['/'] = self._extensions['/'] + 1
        else:
          self._extensions['/'] = 1
        return

      # Strip to a filename
      i = path.rfind('/')
      if i >= 0:
        assert i < len(path)
        path = path[i:]

      # Find extension
      i = path.rfind('.')
      if i > 0:
        assert i < len(path)
        ext = path[i:].lower()
        if self._extensions.has_key(ext):
          self._extensions[ext] = self._extensions[ext] + 1
        else:
          self._extensions[ext] = 1
      else:
        if self._extensions.has_key('(no extension)'):
          self._extensions['(no extension)'] = self._extensions[
            '(no extension)'] + 1
        else:
          self._extensions['(no extension)'] = 1
  #end def Consume

  def Log(self):
    """ Dump out stats to the output. """
    if len(self._extensions):
      output.Log('Count of file extensions on URLs:', 1)
      set = self._extensions.keys()
      set.sort()
      for ext in set:
        output.Log(' %7d  %s' % (self._extensions[ext], ext), 1)
  #end def Log

class Sitemap(xml.sax.handler.ContentHandler):
  """
  This is the big workhorse class that processes your inputs and spits
  out sitemap files.  It is built as a SAX handler for set up purposes.
  That is, it processes an XML stream to bring itself up.
  """

  def __init__(self, suppress_notify):
    xml.sax.handler.ContentHandler.__init__(self)
    self._filters      = []                  # Filter objects
    self._inputs       = []                  # Input objects
    self._urls         = {}                  # Maps URLs to count of dups
    self._set          = []                  # Current set of URLs
    self._filegen      = None                # Path generator for output files
    self._wildurl1     = None                # Sitemap URLs to filter out
    self._wildurl2     = None                # Sitemap URLs to filter out
    self._sitemaps     = 0                   # Number of output files
    # We init _dup_max to 2 so the default priority is 0.5 instead of 1.0
    self._dup_max      = 2                   # Max number of duplicate URLs
    self._stat         = PerURLStatistics()  # Some simple stats
    self._in_site      = False               # SAX: are we in a Site node?
    self._in_Site_ever = False               # SAX: were we ever in a Site?

    self._default_enc  = None                # Best encoding to try on URLs
    self._base_url     = None                # Prefix to all valid URLs
    self._store_into   = None                # Output filepath
    self._suppress     = suppress_notify     # Suppress notify of servers
  #end def __init__

  def ValidateBasicConfig(self):
    """ Verifies (and cleans up) the basic user-configurable options. """
    all_good = True

    if self._default_enc:
      encoder.SetUserEncoding(self._default_enc)

    # Canonicalize the base_url
    if all_good and not self._base_url:
      output.Error('A site needs a "base_url" attribute.')
      all_good = False
    if all_good and not URL.IsAbsolute(self._base_url):
        output.Error('The "base_url" must be absolute, not relative: %s' %
                     self._base_url)
        all_good = False
    if all_good:
      self._base_url = URL.Canonicalize(self._base_url)
      if not self._base_url.endswith('/'):
        self._base_url = self._base_url + '/'
      output.Log('BaseURL is set to: %s' % self._base_url, 2)

    # Load store_into into a generator
    if all_good:
      if self._store_into:
        self._filegen = FilePathGenerator()
        if not self._filegen.Preload(self._store_into):
          all_good = False
      else:
        output.Error('A site needs a "store_into" attribute.')
        all_good = False

    # Ask the generator for patterns on what its output will look like
    if all_good:
      self._wildurl1 = self._filegen.GenerateWildURL(self._base_url)
      self._wildurl2 = self._filegen.GenerateURL(SITEINDEX_SUFFIX,
                                                 self._base_url)

    # Unify various forms of False
    if all_good:
      if self._suppress:
        if (type(self._suppress) == types.StringType) or (type(self._suppress)
                                 == types.UnicodeType):
          if (self._suppress == '0') or (self._suppress.lower() == 'false'):
            self._suppress = False

    # Done
    if not all_good:
      output.Log('See "example_config.xml" for more information.', 0)
    return all_good
  #end def ValidateBasicConfig

  def Generate(self):
    """ Run over all the Inputs and ask them to Produce """
    # Run the inputs
    for input in self._inputs:
      input.ProduceURLs(self.ConsumeURL)

    # Do last flushes
    if len(self._set):
      self.FlushSet()
    if not self._sitemaps:
      output.Warn('No URLs were recorded, writing an empty sitemap.')
      self.FlushSet()

    # Write an index as needed
    if self._sitemaps > 1:
      self.WriteIndex()

    # Notify
    self.NotifySearch()

    # Dump stats
    self._stat.Log()
  #end def Generate

  def ConsumeURL(self, url, allow_fragment):
    """
    All per-URL processing comes together here, regardless of Input.
    Here we run filters, remove duplicates, spill to disk as needed, etc.
    """
    if not url:
      return

    # Validate
    if not url.Validate(self._base_url, allow_fragment):
      return

    # Run filters
    accept = None
    for filter in self._filters:
      accept = filter.Apply(url)
      if accept != None:
        break
    if not (accept or (accept == None)):
      url.Log(prefix='FILTERED', level=2)
      return

    # Ignore our out output URLs
    if fnmatch.fnmatchcase(url.loc, self._wildurl1) or fnmatch.fnmatchcase(
      url.loc, self._wildurl2):
      url.Log(prefix='IGNORED (output file)', level=2)
      return

    # Note the sighting
    hash = url.MakeHash()
    if self._urls.has_key(hash):
      dup = self._urls[hash]
      if dup > 0:
        dup = dup + 1
        self._urls[hash] = dup
        if self._dup_max < dup:
          self._dup_max = dup
      url.Log(prefix='DUPLICATE')
      return

    # Acceptance -- add to set
    self._urls[hash] = 1
    self._set.append(url)
    self._stat.Consume(url)
    url.Log()

    # Flush the set if needed
    if len(self._set) >= MAXURLS_PER_SITEMAP:
      self.FlushSet()
  #end def ConsumeURL

  def FlushSet(self):
    """
    Flush the current set of URLs to the output.  This is a little
    slow because we like to sort them all and normalize the priorities
    before dumping.
    """

    # Sort and normalize
    output.Log('Sorting and normalizing collected URLs.', 1)
    self._set.sort()
    for url in self._set:
      hash = url.MakeHash()
      dup = self._urls[hash]
      if dup > 0:
        self._urls[hash] = -1
        if not url.priority:
          url.priority = '%.4f' % (float(dup) / float(self._dup_max))

    # Get the filename we're going to write to
    filename = self._filegen.GeneratePath(self._sitemaps)
    if not filename:
      output.Fatal('Unexpected: Couldn\'t generate output filename.')
    self._sitemaps = self._sitemaps + 1
    output.Log('Writing Sitemap file "%s" with %d URLs' %
        (filename, len(self._set)), 1)

    # Write to it
    frame = None
    file  = None

    try:
      if self._filegen.is_gzip:
        basename = os.path.basename(filename);
        frame = open(filename, 'wb')
        file = gzip.GzipFile(fileobj=frame, filename=basename, mode='wt')
      else:
        file = open(filename, 'wt')

      file.write(SITEMAP_HEADER)
      for url in self._set:
        url.WriteXML(file)
      file.write(SITEMAP_FOOTER)

      file.close()
      if frame:
        frame.close()

      frame = None
      file  = None
    except IOError:
      output.Fatal('Couldn\'t write out to file: %s' % filename)
    os.chmod(filename, 0644)

    # Flush
    self._set = []
  #end def FlushSet

  def WriteIndex(self):
    """ Write the master index of all Sitemap files """
    # Make a filename
    filename = self._filegen.GeneratePath(SITEINDEX_SUFFIX)
    if not filename:
      output.Fatal('Unexpected: Couldn\'t generate output index filename.')
    output.Log('Writing index file "%s" with %d Sitemaps' %
        (filename, self._sitemaps), 1)

    # Make a lastmod time
    lastmod = TimestampISO8601(time.time())

    # Write to it
    try:
      fd = open(filename, 'wt')
      fd.write(SITEINDEX_HEADER)

      for mapnumber in range(0,self._sitemaps):
        # Write the entry
        mapurl = self._filegen.GenerateURL(mapnumber, self._base_url)
        mapattributes = { 'loc' : mapurl, 'lastmod' : lastmod }
        fd.write(SITEINDEX_ENTRY % mapattributes)

      fd.write(SITEINDEX_FOOTER)

      fd.close()
      fd = None
    except IOError:
      output.Fatal('Couldn\'t write out to file: %s' % filename)
    os.chmod(filename, 0644)
  #end def WriteIndex

  def NotifySearch(self):
    """ Send notification of the new Sitemap(s) to the search engines. """
    if self._suppress:
      output.Log('Search engine notification is suppressed.', 1)
      return

    output.Log('Notifying search engines.', 1)

    # Override the urllib's opener class with one that doesn't ignore 404s
    class ExceptionURLopener(urllib.FancyURLopener):
      def http_error_default(self, url, fp, errcode, errmsg, headers):
        output.Log('HTTP error %d: %s' % (errcode, errmsg), 2)
        raise IOError
      #end def http_error_default
    #end class ExceptionURLOpener
    old_opener = urllib._urlopener
    urllib._urlopener = ExceptionURLopener()

    # Build the URL we want to send in
    if self._sitemaps > 1:
      url = self._filegen.GenerateURL(SITEINDEX_SUFFIX, self._base_url)
    else:
      url = self._filegen.GenerateURL(0, self._base_url)

    # Test if we can hit it ourselves
    try:
      u = urllib.urlopen(url)
      u.close()
    except IOError:
      output.Error('When attempting to access our generated Sitemap at the '
                   'following URL:\n    %s\n  we failed to read it.  Please '
                   'verify the store_into path you specified in\n'
                   '  your configuration file is web-accessable.  Consult '
                   'the FAQ for more\n  information.' % url)
      output.Warn('Proceeding to notify with an unverifyable URL.')

    # Cycle through notifications
    # To understand this, see the comment near the NOTIFICATION_SITES comment
    for ping in NOTIFICATION_SITES:
      query_map             = ping[3]
      query_attr            = ping[5]
      query_map[query_attr] = url
      query = urllib.urlencode(query_map)
      notify = urlparse.urlunsplit((ping[0], ping[1], ping[2], query, ping[4]))

      # Send the notification
      output.Log('Notifying: %s' % ping[1], 1)
      output.Log('Notification URL: %s' % notify, 2)
      try:
        u = urllib.urlopen(notify)
        u.read()
        u.close()
      except IOError:
        output.Warn('Cannot contact: %s' % ping[1])

    if old_opener:
      urllib._urlopener = old_opener
  #end def NotifySearch

  def startElement(self, tag, attributes):
    """ SAX processing, called per node in the config stream. """

    if tag == 'site':
      if self._in_site:
        output.Error('Can not nest Site entries in the configuration.')
      else:
        self._in_site     = True

        if not ValidateAttributes('SITE', attributes,
          ('verbose', 'default_encoding', 'base_url', 'store_into',
           'suppress_search_engine_notify')):
          return

        verbose           = attributes.get('verbose', 0)
        if verbose:
          output.SetVerbose(verbose)

        self._default_enc = attributes.get('default_encoding')
        self._base_url    = attributes.get('base_url')
        self._store_into  = attributes.get('store_into')
        if not self._suppress:
          self._suppress  = attributes.get('suppress_search_engine_notify',
                                            False)
        self.ValidateBasicConfig()

    elif tag == 'filter':
      self._filters.append(Filter(attributes))

    elif tag == 'url':
      self._inputs.append(InputURL(attributes))

    elif tag == 'urllist':
      for attributeset in ExpandPathAttribute(attributes, 'path'):
        self._inputs.append(InputURLList(attributeset))

    elif tag == 'directory':
      self._inputs.append(InputDirectory(attributes, self._base_url))

    elif tag == 'accesslog':
      for attributeset in ExpandPathAttribute(attributes, 'path'):
        self._inputs.append(InputAccessLog(attributeset))

    elif tag == 'sitemap':
      for attributeset in ExpandPathAttribute(attributes, 'path'):
        self._inputs.append(InputSitemap(attributeset))

    else:
      output.Error('Unrecognized tag in the configuration: %s' % tag)
  #end def startElement

  def endElement(self, tag):
    """ SAX processing, called per node in the config stream. """
    if tag == 'site':
      assert self._in_site
      self._in_site      = False
      self._in_site_ever = True
  #end def endElement

  def endDocument(self):
    """ End of SAX, verify we can proceed. """
    if not self._in_site_ever:
      output.Error('The configuration must specify a "site" element.')
    else:
      if not self._inputs:
        output.Warn('There were no inputs to generate a sitemap from.')
  #end def endDocument
#end class Sitemap


def ValidateAttributes(tag, attributes, goodattributes):
  """ Makes sure 'attributes' does not contain any attribute not
      listed in 'goodattributes' """
  all_good = True
  for attr in attributes.keys():
    if not attr in goodattributes:
      output.Error('Unknown %s attribute: %s' % (tag, attr))
      all_good = False
  return all_good
#end def ValidateAttributes

def ExpandPathAttribute(src, attrib):
  """ Given a dictionary of attributes, return a list of dictionaries
      with all the same attributes except for the one named attrib.
      That one, we treat as a file path and expand into all its possible
      variations. """
  # Do the path expansion.  On any error, just return the source dictionary.
  path = src.get(attrib)
  if not path:
    return [src]
  path = encoder.MaybeNarrowPath(path);
  pathlist = glob.glob(path)
  if not pathlist:
    return [src]

  # If this isn't actually a dictionary, make it one
  if type(src) != types.DictionaryType:
    tmp = {}
    for key in src.keys():
      tmp[key] = src[key]
    src = tmp

  # Create N new dictionaries
  retval = []
  for path in pathlist:
    dst = src.copy()
    dst[attrib] = path
    retval.append(dst)

  return retval
#end def ExpandPathAttribute

def OpenFileForRead(path, logtext):
  """ Opens a text file, be it GZip or plain """

  frame = None
  file  = None

  if not path:
    return (frame, file)

  try:
    if path.endswith('.gz'):
      frame = open(path, 'rb')
      file = gzip.GzipFile(fileobj=frame, mode='rt')
    else:
      file = open(path, 'rt')

    if logtext:
      output.Log('Opened %s file: %s' % (logtext, path), 1)
    else:
      output.Log('Opened file: %s' % path, 1)
  except IOError:
    output.Error('Can not open file: %s' % path)

  return (frame, file)
#end def OpenFileForRead

def TimestampISO8601(t):
  """Seconds since epoch (1970-01-01) --> ISO 8601 time string."""
  return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t))
#end def TimestampISO8601

def CreateSitemapFromFile(configpath, suppress_notify):
  """ Sets up a new Sitemap object from the specified configuration file.  """

  # Remember error count on the way in
  num_errors = output.num_errors

  # Rev up SAX to parse the config
  sitemap = Sitemap(suppress_notify)
  try:
    output.Log('Reading configuration file: %s' % configpath, 0)
    xml.sax.parse(configpath, sitemap)
  except IOError:
    output.Error('Cannot read configuration file: %s' % configpath)
  except xml.sax._exceptions.SAXParseException, e:
    output.Error('XML error in the config file (line %d, column %d): %s' %
                 (e._linenum, e._colnum, e.getMessage()))
  except xml.sax._exceptions.SAXReaderNotAvailable:
    output.Error('Some installs of Python 2.2 did not include complete support'
                 ' for XML.\n  Please try upgrading your version of Python'
                 ' and re-running the script.')

  # If we added any errors, return no sitemap
  if num_errors == output.num_errors:
    return sitemap
  return None
#end def CreateSitemapFromFile

def ProcessCommandFlags(args):
  """
  Parse command line flags per specified usage, pick off key, value pairs
  All flags of type "--key=value" will be processed as __flags[key] = value,
                    "--option" will be processed as __flags[option] = option
  """

  flags   = {}
  rkeyval = '--(?P<key>\S*)[=](?P<value>\S*)' # --key=val
  roption = '--(?P<option>\S*)'               # --key
  r = '(' + rkeyval + ')|(' + roption + ')'
  rc = re.compile(r)
  for a in args:
    try:
      rcg = rc.search(a).groupdict()
      if rcg.has_key('key'):
        flags[rcg['key']] = rcg['value']
      if rcg.has_key('option'):
        flags[rcg['option']] = rcg['option']
    except AttributeError:
      return None
  return flags
#end def ProcessCommandFlags


#
# __main__
#

if __name__ == '__main__':
  flags = ProcessCommandFlags(sys.argv[1:])
  if not flags or not flags.has_key('config') or flags.has_key('help'):
    output.Log(__usage__, 0)
  else:
    suppress_notify = flags.has_key('testing')
    sitemap = CreateSitemapFromFile(flags['config'], suppress_notify)
    if not sitemap:
      output.Log('Configuration file errors -- exiting.', 0)
    else:
      sitemap.Generate()
      output.Log('Number of errors: %d' % output.num_errors, 1)
      output.Log('Number of warnings: %d' % output.num_warns, 1)
