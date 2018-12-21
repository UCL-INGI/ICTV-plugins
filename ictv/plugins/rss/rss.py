# -*- coding: utf-8 -*-
#
#    This file belongs to the ICTV project, written by Nicolas Detienne,
#    Francois Michel, Maxime Piraux, Pierre Reinbold and Ludovic Taffin
#    at Université catholique de Louvain.
#
#    Copyright (C) 2016-2018  Université catholique de Louvain (UCL, Belgium)
#
#    ICTV is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published
#    by the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    ICTV is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with ICTV.  If not, see <http://www.gnu.org/licenses/>.

import json
import os
import re
import urllib.request
import urllib.response
from datetime import datetime, timedelta
from time import mktime

import fcntl
from urllib.parse import urljoin

import feedparser
import zlib

from ictv.common import get_root_path
from ictv.common.json_datetime import DateTimeDecoder, DateTimeEncoder
from ictv.models.channel import Channel
from ictv.plugin_manager.plugin_capsule import PluginCapsule
from ictv.plugin_manager.plugin_manager import get_logger, _is_url
from ictv.plugin_manager.plugin_slide import PluginSlide

this_group = 'this' # when searching for regular expression matches, we search
                    # for a group named (?P<this>) in the regexp. If there is
                    # such a group, we return the match of that group, if not,
                    # we return the entire matching (if any).

cache_path = os.path.join(os.path.dirname(__file__), 'cache.json')
if not os.path.exists(cache_path):
    with open(cache_path, 'w') as f:
        json.dump({}, f)


def get_content(channel_id, config=None):
    channel = Channel.get(channel_id)
    logger = get_logger('rss', channel)
    if not config:
        def get_param(x): return channel.get_config_param(x)
    else:
        def get_param(x): return config[x]

    url = get_param('url')
    parser_rules = get_param('parser_rules')  # A list of rules in the form slide_element;entry_item;regexp
    additional_rules = get_param('additional_rules')  # A list of rules in the form entry_item;string
    filter = get_param('filter')
    exception_rules = get_param('exception_rules')  # A list of rules in the form entry_item;string
    no_slides = get_param('no_slides')
    time_limit = get_param('time_limit')
    duration = get_param('duration') * 1000
    template = get_param('template')
    theme = get_param('theme')
    min_age = datetime.now() - timedelta(days=time_limit)

    entries = feedparser_parse(url)['entries'][:no_slides] if not config or not config.get('feed') else config.get('feed')
    capsules = []
    last_entries = []

    with open(cache_path, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        cache = json.load(f, cls=DateTimeDecoder)

        for entry in entries:
            if 'published_parsed' in entry:
                entry_age = datetime.fromtimestamp(mktime(entry['published_parsed']))
                if entry_age >= min_age:
                    last_entries.append(entry)
            else:
                entry_hash = hash_dict(entry)
                if entry_hash in cache:
                    if cache[entry_hash] >= min_age:
                        last_entries.append(entry)
                else:
                    cache[entry_hash] = datetime.now()
        f.seek(0)
        json.dump(cache, f, cls=DateTimeEncoder)
        f.truncate()
        fcntl.flock(f, fcntl.LOCK_UN)

    for entry in last_entries:
        slide_content = {}
        link_page = None
        for slide_element, entry_item, regexp in [rule.split(';') for rule in parser_rules]:
            field, input_type = slide_element.split(':')
            if field not in slide_content:
                slide_content[field] = {}

            if entry_item == 'link_page':
                if not link_page:
                    with urllib.request.urlopen(entry.link) as response:
                        link_page = response.read().decode(errors='ignore')
                        entry_item += "@" + response.geturl() # in case of redirect(s), geturl() returns the final url of the page
                item = link_page
            else:
                item = deep_get(entry, *entry_item.split('.'))

            value = get_value(item, regexp)
            if input_type == 'src' and not _is_url(value):
                ref_url = entry.link
                if entry_item.startswith('link_page@'):
                    ref_url = entry_item.split('@')[1]
                value = urljoin(ref_url, value)

            slide_content[field].update({input_type: value})

        for slide_element, string in [rule.split(';') for rule in additional_rules]:
            field, input_type = slide_element.split(':')
            if field not in slide_content:
                slide_content[field] = {}
            if string.lower() == 'qrcode':
                input_type = 'qrcode'
                string = entry.link
            slide_content[field].update({input_type: string})

        if len(exception_rules) == 1 and not exception_rules[0].strip():
            capsules.append(RssCapsule(theme=theme, slides=[RssSlide(content=slide_content, template=template, duration=duration)]))
        else:
            for entry_item, regexp in [rule.split(';') for rule in exception_rules]:
                if entry_item == 'link_page':
                    if not link_page:
                        with urllib.request.urlopen(entry.link) as response:
                            link_page = response.read().decode(errors='ignore')
                            entry_item += "@" + response.geturl() # in case of redirect(s), geturl() returns the final url of the page
                    item = link_page
                else:
                    item = deep_get(entry, *entry_item.split('.'))

                value = get_value(item, regexp)

                if filter and value is None:
                    capsules.append(RssCapsule(theme=theme, slides=[RssSlide(content=slide_content, template=template, duration=duration)]))

                if not filter and value is not None:
                    capsules.append(RssCapsule(theme=theme, slides=[RssSlide(content=slide_content, template=template, duration=duration)]))

    return capsules


def get_value(item, regexp):
    pattern = re.compile(regexp, re.DOTALL | re.MULTILINE)
    match = pattern.search(item)
    if match:
        if this_group in pattern.groupindex:
            return match.group(this_group)
        else:
            return match.group()
    return None

# pattern corresponding to access to list item inside XML elem tree
gr_list_name = "name"
gr_list_index = "index"
list_regexp = r"(?P<" + gr_list_name+ ">[^[]+)\[(?P<" + gr_list_index + ">[0-9]+)\]"
list_pattern = re.compile(list_regexp, re.DOTALL | re.MULTILINE)
def deep_get(d, *keys):
    for key in keys:
        list_match = list_pattern.search(key)
        if list_match:
            name = list_match.group(gr_list_name)
            index = int(list_match.group(gr_list_index))
            d = d[name][index]
        else:
            d = d[key]
    return d


def hash_dict(d):
    return hex(zlib.adler32(json.dumps(d, sort_keys=True, ensure_ascii=True).encode()))


class RssSlide(PluginSlide):
    def __init__(self, content, template, duration):
        self.content = content
        self.template = template
        self.duration = duration

    def get_template(self) -> str:
        return self.template

    def get_duration(self):
        return self.duration

    def get_content(self):
        return self.content


class RssCapsule(PluginCapsule):
    def __init__(self, theme, slides):
        self.theme = theme
        self.slides = slides

    def get_slides(self):
        return self.slides

    def get_theme(self) -> str:
        return self.theme


def feedparser_parse(uri):
    try:
        return feedparser.parse(uri)
    except TypeError:
        if 'drv_libxml2' in feedparser.PREFERRED_XML_PARSERS:
            feedparser.PREFERRED_XML_PARSERS.remove('drv_libxml2')
            return feedparser.parse(uri)
        else:
            raise
