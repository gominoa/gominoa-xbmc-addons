# This file is part of the musicbrainzngs library
# Copyright (C) Alastair Porter, Adrian Sampson, and others
# This file is distributed under a BSD-2-Clause type license.
# See the COPYING file for more information.

import re
import xml.etree.ElementTree as ET
import logging

from musicbrainzngs import util

try:
    from ET import fixtag
except:
    # Python < 2.7
    def fixtag(tag, namespaces):
        # given a decorated tag (of the form {uri}tag), return prefixed
        # tag and namespace declaration, if any
        if isinstance(tag, ET.QName):
            tag = tag.text
        namespace_uri, tag = tag[1:].split("}", 1)
        prefix = namespaces.get(namespace_uri)
        if prefix is None:
            prefix = "ns%d" % len(namespaces)
            namespaces[namespace_uri] = prefix
            if prefix == "xml":
                xmlns = None
            else:
                xmlns = ("xmlns:%s" % prefix, namespace_uri)
        else:
            xmlns = None
        return "%s:%s" % (prefix, tag), xmlns


NS_MAP = {"http://musicbrainz.org/ns/mmd-2.0#": "ws2",
          "http://musicbrainz.org/ns/ext#-2.0": "ext"}
_log = logging.getLogger("musicbrainzngs")


def parse_elements(valid_els, inner_els, element):
    """ Extract single level subelements from an element.
        For example, given the element:
        <element>
            <subelement>Text</subelement>
        </element>
        and a list valid_els that contains "subelement",
        return a dict {'subelement': 'Text'}

        Delegate the parsing of multi-level subelements to another function.
        For example, given the element:
        <element>
            <subelement>
                <a>Foo</a><b>Bar</b>
            </subelement>
        </element>
        and a dictionary {'subelement': parse_subelement},
        call parse_subelement(<subelement>) and
        return a dict {'subelement': <result>}
        if parse_subelement returns a tuple of the form
        ('subelement-key', <result>) then return a dict
        {'subelement-key': <result>} instead
    """
    result = {}
    for sub in element:
        t = fixtag(sub.tag, NS_MAP)[0]
        if ":" in t:
            t = t.split(":")[1]
        if t in valid_els:
            result[t] = sub.text or ""
        elif t in inner_els.keys():
            inner_result = inner_els[t](sub)
            if isinstance(inner_result, tuple):
                result[inner_result[0]] = inner_result[1]
            else:
                result[t] = inner_result
            # add counts for lists when available
            m = re.match(r'([a-z0-9-]+)-list', t)
            if m and "count" in sub.attrib:
                result["%s-count" % m.group(1)] = int(sub.attrib["count"])
        else:
            _log.info("in <%s>, uncaught <%s>",
                      fixtag(element.tag, NS_MAP)[0], t)
    return result


def parse_attributes(attributes, element):
    """ Extract attributes from an element.
        For example, given the element:
        <element type="Group" />
        and a list attributes that contains "type",
        return a dict {'type': 'Group'}
    """
    result = {}
    for attr in element.attrib:
        if "{" in attr:
            a = fixtag(attr, NS_MAP)[0]
        else:
            a = attr
        if a in attributes:
            result[a] = element.attrib[attr]
        else:
            _log.info("in <%s>, uncaught attribute %s", fixtag(element.tag, NS_MAP)[0], attr)

    return result


def parse_message(message):
    tree = util.bytes_to_elementtree(message)
    root = tree.getroot()
    result = {}
    valid_elements = { "recording-list": parse_recording_list }
    result.update(parse_elements([], valid_elements, root))
    return result


def parse_recording(recording):
    result = {}
    attribs = ["id", "ext:score"]
    result.update(parse_attributes(attribs, recording))
    return result


def parse_recording_list(recs):
    result = []
    for r in recs:
        result.append(parse_recording(r))
    return result

