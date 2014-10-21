# This file is part of the musicbrainzngs library
# Copyright (C) Alastair Porter, Adrian Sampson, and others
# This file is distributed under a BSD-2-Clause type license.
# See the COPYING file for more information.

import re
import threading
import time
import logging
import socket
import hashlib
import locale
import sys
import xml.etree.ElementTree as etree
from xml.parsers import expat
from warnings import warn, simplefilter

from musicbrainzngs import mbxml
from musicbrainzngs import util
from musicbrainzngs import compat

_version = "0.5"
_log = logging.getLogger("musicbrainzngs")

# turn on DeprecationWarnings below
simplefilter(action="once", category=DeprecationWarning)


# Constants for validation.

RELATABLE_TYPES = ['area', 'artist', 'label', 'place', 'recording', 'release', 'release-group', 'url', 'work']
RELATION_INCLUDES = [entity + '-rels' for entity in RELATABLE_TYPES]
TAG_INCLUDES = ["tags", "user-tags"]
RATING_INCLUDES = ["ratings", "user-ratings"]

VALID_INCLUDES = {
    'recording': [
        "artists", "releases", # Subqueries
        "discids", "media", "artist-credits", "isrcs",
        "annotation", "aliases"
    ] + TAG_INCLUDES + RATING_INCLUDES + RELATION_INCLUDES,
}

VALID_SEARCH_FIELDS = {
    'recording': [
        'arid', 'artist', 'artistname', 'creditname', 'comment',
        'country', 'date', 'dur', 'format', 'isrc', 'number',
        'position', 'primarytype', 'puid', 'qdur', 'recording',
        'recordingaccent', 'reid', 'release', 'rgid', 'rid',
        'secondarytype', 'status', 'tnum', 'tracks', 'tracksrelease',
        'tag', 'type', 'video'
    ],
}


# Exceptions.

class MusicBrainzError(Exception):
	"""Base class for all exceptions related to MusicBrainz."""
	pass

class UsageError(MusicBrainzError):
	"""Error related to misuse of the module API."""
	pass

class InvalidSearchFieldError(UsageError):
	pass

class InvalidIncludeError(UsageError):
	def __init__(self, msg='Invalid Includes', reason=None):
		super(InvalidIncludeError, self).__init__(self)
		self.msg = msg
		self.reason = reason

	def __str__(self):
		return self.msg

class WebServiceError(MusicBrainzError):
	"""Error related to MusicBrainz API requests."""
	def __init__(self, message=None, cause=None):
		"""Pass ``cause`` if this exception was caused by another
		exception.
		"""
		self.message = message
		self.cause = cause

	def __str__(self):
		if self.message:
			msg = "%s, " % self.message
		else:
			msg = ""
		msg += "caused by: %s" % str(self.cause)
		return msg

class NetworkError(WebServiceError):
	"""Problem communicating with the MB server."""
	pass

class ResponseError(WebServiceError):
	"""Bad response sent by the MB server."""
	pass

class AuthenticationError(WebServiceError):
	"""Received a HTTP 401 response while accessing a protected resource."""
	pass


# Helpers for validating and formatting allowed sets.

def _check_includes_impl(includes, valid_includes):
    for i in includes:
        if i not in valid_includes:
            raise InvalidIncludeError("Bad includes: "
                                      "%s is not a valid include" % i)
def _check_includes(entity, inc):
    _check_includes_impl(inc, VALID_INCLUDES[entity])

def _docstring(entity, browse=False):
    def _decorator(func):
        if browse:
            includes = list(VALID_BROWSE_INCLUDES.get(entity, []))
        else:
            includes = list(VALID_INCLUDES.get(entity, []))
        # puids are allowed so nothing breaks, but not documented
        if "puids" in includes: includes.remove("puids")
        includes = ", ".join(includes)
        if func.__doc__:
            search_fields = list(VALID_SEARCH_FIELDS.get(entity, []))
            # puid is allowed so nothing breaks, but not documented
            if "puid" in search_fields: search_fields.remove("puid")
            func.__doc__ = func.__doc__.format(includes=includes,
                    fields=", ".join(search_fields))
        return func

    return _decorator


# Global authentication and endpoint details.

user = password = ""
hostname = "musicbrainz.org"
_client = ""
_useragent = ""

def set_useragent(app, version, contact=None):
    """Set the User-Agent to be used for requests to the MusicBrainz webservice.
    This must be set before requests are made."""
    global _useragent, _client
    if not app or not version:
        raise ValueError("App and version can not be empty")
    if contact is not None:
        _useragent = "%s/%s python-musicbrainzngs/%s ( %s )" % (app, version, _version, contact)
    else:
        _useragent = "%s/%s python-musicbrainzngs/%s" % (app, version, _version)
    _client = "%s-%s" % (app, version)
    _log.debug("set user-agent to %s" % _useragent)

# Rate limiting.

limit_interval = 1.0
limit_requests = 1
do_rate_limit = True

class _rate_limit(object):
    """A decorator that limits the rate at which the function may be
    called. The rate is controlled by the `limit_interval` and
    `limit_requests` global variables.  The limiting is thread-safe;
    only one thread may be in the function at a time (acts like a
    monitor in this sense). The globals must be set before the first
    call to the limited function.
    """
    def __init__(self, fun):
        self.fun = fun
        self.last_call = 0.0
        self.lock = threading.Lock()
        self.remaining_requests = None # Set on first invocation.

    def _update_remaining(self):
        """Update remaining requests based on the elapsed time since
        they were last calculated.
        """
        # On first invocation, we have the maximum number of requests
        # available.
        if self.remaining_requests is None:
            self.remaining_requests = float(limit_requests)

        else:
            since_last_call = time.time() - self.last_call
            self.remaining_requests += since_last_call * \
                                       (limit_requests / limit_interval)
            self.remaining_requests = min(self.remaining_requests,
                                          float(limit_requests))

        self.last_call = time.time()

    def __call__(self, *args, **kwargs):
        with self.lock:
            if do_rate_limit:
                self._update_remaining()

                # Delay if necessary.
                while self.remaining_requests < 0.999:
                    time.sleep((1.0 - self.remaining_requests) *
                               (limit_requests / limit_interval))
                    self._update_remaining()

                # Call the original function, "paying" for this call.
                self.remaining_requests -= 1.0
            return self.fun(*args, **kwargs)

# From pymb2
class _RedirectPasswordMgr(compat.HTTPPasswordMgr):
	def __init__(self):
		self._realms = { }

	def find_user_password(self, realm, uri):
		# ignoring the uri parameter intentionally
		try:
			return self._realms[realm]
		except KeyError:
			return (None, None)

	def add_password(self, realm, uri, username, password):
		# ignoring the uri parameter intentionally
		self._realms[realm] = (username, password)

class _DigestAuthHandler(compat.HTTPDigestAuthHandler):
    def get_authorization (self, req, chal):
        qop = chal.get ('qop', None)
        if qop and ',' in qop and 'auth' in qop.split (','):
            chal['qop'] = 'auth'

        return compat.HTTPDigestAuthHandler.get_authorization (self, req, chal)

    def _encode_utf8(self, msg):
        """The MusicBrainz server also accepts UTF-8 encoded passwords."""
        encoding = sys.stdin.encoding or locale.getpreferredencoding()
        try:
            # This works on Python 2 (msg in bytes)
            msg = msg.decode(encoding)
        except AttributeError:
            # on Python 3 (msg is already in unicode)
            pass
        return msg.encode("utf-8")

    def get_algorithm_impls(self, algorithm):
        # algorithm should be case-insensitive according to RFC2617
        algorithm = algorithm.upper()
        # lambdas assume digest modules are imported at the top level
        if algorithm == 'MD5':
            H = lambda x: hashlib.md5(self._encode_utf8(x)).hexdigest()
        elif algorithm == 'SHA':
            H = lambda x: hashlib.sha1(self._encode_utf8(x)).hexdigest()
        # XXX MD5-sess
        KD = lambda s, d: H("%s:%s" % (s, d))
        return H, KD

class _MusicbrainzHttpRequest(compat.Request):
	""" A custom request handler that allows DELETE and PUT"""
	def __init__(self, method, url, data=None):
		compat.Request.__init__(self, url, data)
		allowed_m = ["GET", "POST", "DELETE", "PUT"]
		if method not in allowed_m:
			raise ValueError("invalid method: %s" % method)
		self.method = method

	def get_method(self):
		return self.method


# Core (internal) functions for calling the MB API.

def _safe_read(opener, req, body=None, max_retries=8, retry_delay_delta=2.0):
	"""Open an HTTP request with a given URL opener and (optionally) a
	request body. Transient errors lead to retries.  Permanent errors
	and repeated errors are translated into a small set of handleable
	exceptions. Return a bytestring.
	"""
	last_exc = None
	for retry_num in range(max_retries):
		if retry_num: # Not the first try: delay an increasing amount.
			_log.info("retrying after delay (#%i)" % retry_num)
			time.sleep(retry_num * retry_delay_delta)

		try:
			if body:
				f = opener.open(req, body)
			else:
				f = opener.open(req)
			return f.read()

		except compat.HTTPError as exc:
			if exc.code in (400, 404, 411):
				# Bad request, not found, etc.
				raise ResponseError(cause=exc)
			elif exc.code in (503, 502, 500):
				# Rate limiting, internal overloading...
				_log.info("HTTP error %i" % exc.code)
			elif exc.code in (401, ):
				raise AuthenticationError(cause=exc)
			else:
				# Other, unknown error. Should handle more cases, but
				# retrying for now.
				_log.info("unknown HTTP error %i" % exc.code)
			last_exc = exc
		except compat.BadStatusLine as exc:
			_log.info("bad status line")
			last_exc = exc
		except compat.HTTPException as exc:
			_log.info("miscellaneous HTTP exception: %s" % str(exc))
			last_exc = exc
		except compat.URLError as exc:
			if isinstance(exc.reason, socket.error):
				code = exc.reason.errno
				if code == 104: # "Connection reset by peer."
					continue
			raise NetworkError(cause=exc)
		except socket.timeout as exc:
			_log.info("socket timeout")
			last_exc = exc
		except socket.error as exc:
			if exc.errno == 104:
				continue
			raise NetworkError(cause=exc)
		except IOError as exc:
			raise NetworkError(cause=exc)

	# Out of retries!
	raise NetworkError("retried %i times" % max_retries, last_exc)

# Get the XML parsing exceptions to catch. The behavior chnaged with Python 2.7
# and ElementTree 1.3.
if hasattr(etree, 'ParseError'):
	ETREE_EXCEPTIONS = (etree.ParseError, expat.ExpatError)
else:
	ETREE_EXCEPTIONS = (expat.ExpatError)


# Parsing setup

def mb_parser_xml(resp):
    """Return a Python dict representing the XML response"""
    # Parse the response.
    try:
        return mbxml.parse_message(resp)
    except UnicodeError as exc:
        raise ResponseError(cause=exc)
    except Exception as exc:
        if isinstance(exc, ETREE_EXCEPTIONS):
            raise ResponseError(cause=exc)
        else:
            raise

# Defaults
parser_fun = mb_parser_xml
ws_format = "xml"


@_rate_limit
def _mb_request(path, method='GET', auth_required=False, client_required=False,
                args=None, data=None, body=None):
    """Makes a request for the specified `path` (endpoint) on /ws/2 on
    the globally-specified hostname. Parses the responses and returns
    the resulting object.  `auth_required` and `client_required` control
    whether exceptions should be raised if the client and
    username/password are left unspecified, respectively.
    """
    global parser_fun 

    if args is None:
        args = {}
    else:
        args = dict(args) or {}

    if _useragent == "":
        raise UsageError("set a proper user-agent with "
                         "set_useragent(\"application name\", \"application version\", \"contact info (preferably URL or email for your application)\")")

    if client_required:
        args["client"] = _client

    if ws_format != "xml":
        args["fmt"] = ws_format

    # Convert args from a dictionary to a list of tuples
    # so that the ordering of elements is stable for easy
    # testing (in this case we order alphabetically)
    # Encode Unicode arguments using UTF-8.
    newargs = []
    for key, value in sorted(args.items()):
        if isinstance(value, compat.unicode):
            value = value.encode('utf8')
        newargs.append((key, value))

    # Construct the full URL for the request, including hostname and
    # query string.
    url = compat.urlunparse((
        'http',
        hostname,
        '/ws/2/%s' % path,
        '',
        compat.urlencode(newargs),
        ''
    ))
    _log.debug("%s request for %s" % (method, url))

    # Set up HTTP request handler and URL opener.
    httpHandler = compat.HTTPHandler(debuglevel=0)
    handlers = [httpHandler]

    # Add credentials if required.
    if auth_required:
        _log.debug("Auth required for %s" % url)
        if not user:
            raise UsageError("authorization required; "
                             "use auth(user, pass) first")
        passwordMgr = _RedirectPasswordMgr()
        authHandler = _DigestAuthHandler(passwordMgr)
        authHandler.add_password("musicbrainz.org", (), user, password)
        handlers.append(authHandler)

    opener = compat.build_opener(*handlers)

    # Make request.
    req = _MusicbrainzHttpRequest(method, url, data)
    req.add_header('User-Agent', _useragent)
    _log.debug("requesting with UA %s" % _useragent)
    if body:
        req.add_header('Content-Type', 'application/xml; charset=UTF-8')
    elif not data and not req.has_header('Content-Length'):
        # Explicitly indicate zero content length if no request data
        # will be sent (avoids HTTP 411 error).
        req.add_header('Content-Length', '0')
    resp = _safe_read(opener, req, body)

    return parser_fun(resp)

def _is_auth_required(entity, includes):
	""" Some calls require authentication. This returns
	True if a call does, False otherwise
	"""
	if "user-tags" in includes or "user-ratings" in includes:
		return True
	elif entity.startswith("collection"):
		return True
	else:
		return False

def _do_mb_query(entity, id, includes=[], params={}):
	"""Make a single GET call to the MusicBrainz XML API. `entity` is a
	string indicated the type of object to be retrieved. The id may be
	empty, in which case the query is a search. `includes` is a list
	of strings that must be valid includes for the entity type. `params`
	is a dictionary of additional parameters for the API call. The
	response is parsed and returned.
	"""
	# Build arguments.
	if not isinstance(includes, list):
		includes = [includes]
	_check_includes(entity, includes)
	auth_required = _is_auth_required(entity, includes)
	args = dict(params)
	if len(includes) > 0:
		inc = " ".join(includes)
		args["inc"] = inc

	# Build the endpoint components.
	path = '%s/%s' % (entity, id)
	return _mb_request(path, 'GET', auth_required, args=args)

def _do_mb_search(entity, query='', fields={},
		  limit=None, offset=None, strict=False):
	"""Perform a full-text search on the MusicBrainz search server.
	`query` is a lucene query string when no fields are set,
	but is escaped when any fields are given. `fields` is a dictionary
	of key/value query parameters. They keys in `fields` must be valid
	for the given entity type.
	"""
	# Encode the query terms as a Lucene query string.
	query_parts = []
	if query:
		clean_query = util._unicode(query)
		if fields:
			clean_query = re.sub(r'([+\-&|!(){}\[\]\^"~*?:\\])',
					r'\\\1', clean_query)
			if strict:
				query_parts.append('"%s"' % clean_query)
			else:
				query_parts.append(clean_query.lower())
		else:
			query_parts.append(clean_query)
	for key, value in fields.items():
		# Ensure this is a valid search field.
		if key not in VALID_SEARCH_FIELDS[entity]:
			raise InvalidSearchFieldError(
				'%s is not a valid search field for %s' % (key, entity)
			)
		elif key == "puid":
			warn("PUID support was removed from server\n"
			     "the 'puid' field is ignored",
			     DeprecationWarning, stacklevel=2)

		# Escape Lucene's special characters.
		value = util._unicode(value)
		value = re.sub(r'([+\-&|!(){}\[\]\^"~*?:\\\/])', r'\\\1', value)
		if value:
			if strict:
				query_parts.append('%s:"%s"' % (key, value))
			else:
				value = value.lower() # avoid AND / OR
				query_parts.append('%s:(%s)' % (key, value))
	if strict:
		full_query = ' AND '.join(query_parts).strip()
	else:
		full_query = ' '.join(query_parts).strip()

	if not full_query:
		raise ValueError('at least one query term is required')

	# Additional parameters to the search.
	params = {'query': full_query}
	if limit:
		params['limit'] = str(limit)
	if offset:
		params['offset'] = str(offset)

	return _do_mb_query(entity, '', [], params)

@_docstring('recording')
def search_recordings(query='', limit=None, offset=None,
                      strict=False, **fields):
    """Search for recordings and return a dict with a 'recording-list' key.

    *Available search fields*: {fields}"""
    return _do_mb_search('recording', query, fields, limit, offset, strict)

