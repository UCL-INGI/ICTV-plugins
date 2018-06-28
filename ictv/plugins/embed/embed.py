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

import hashlib
import os

import time
import urllib
from urllib.error import URLError

import ictv.plugin_manager.plugin_manager
from ictv.common import get_root_path
from ictv.models.channel import PluginChannel
from ictv.plugin_manager.plugin_capsule import PluginCapsule
from ictv.plugin_manager.plugin_slide import PluginSlide
from ictv.plugin_manager.plugin_utils import MisconfiguredParameters
from ictv.plugins.embed.inliner import inline

static_dir = os.path.join(os.path.dirname(__file__), 'static')
if not os.path.exists(static_dir):
    os.mkdir(static_dir)


def get_content(channel_id):
    channel = PluginChannel.get(channel_id)
    logger_extra = {'channel_name': channel.name, 'channel_id': channel.id}
    logger = ictv.plugin_manager.plugin_manager.get_logger('embed', channel)
    link = channel.get_config_param('link')
    file_hash = get_file_hash(channel_id, link)
    width = channel.get_config_param('width')
    height = channel.get_config_param('height')
    refresh_rate = channel.get_config_param('refresh_rate')
    duration = channel.get_config_param('duration')
    if link is None or height is None or width is None or duration is None:
        logger.warning('Some of the parameters are missing', extra=logger_extra)
        return []

    iframe_path, full_iframe_path, inlined_page, full_inlined_page_path = get_paths(file_hash)

    if not os.path.exists(full_iframe_path) or os.path.getmtime(full_iframe_path) + (refresh_rate * 60 * 60) < int(time.time()):
        logger.debug('Rebuilding cache', extra=logger_extra)
        # No cache exists or it has expired
        scripts = []
        if channel.get_config_param('jquery'):
            scripts.append('/static/plugins/embed/js/jquery.min.js')
        if channel.get_config_param('jquery_ui'):
            scripts.append('/static/plugins/embed/js/jquery-ui.min.js')
        try:
            inline(link, full_inlined_page_path, logger, scripts)
        except URLError as e:
            raise MisconfiguredParameters('link', link, 'The following error was encountered: %s.' % str(e))
        iframe_path = create_iframe_page('/static/' + inlined_page, width, height, file_hash)
    return [EmbedCapsule(iframe_path, duration * 1000)]


def create_iframe_page(src, width, height, file_hash):
    html = """<html>
            <head>
                <meta charset="UTF-8">
                <title></title>
            </head>
            <body style="margin: 0;">
                <iframe scrolling="no" src="{0}" width="{1}" height="{2}"
                        frameborder="0" marginwidth="0" marginheight="0">
                </iframe>
                <script>
                    function resize() {{
                        var width = window.innerWidth
                                || document.documentElement.clientWidth
                                || document.body.clientWidth;

                        var height = window.innerHeight
                                || document.documentElement.clientHeight
                                || document.body.clientHeight;

                        var iframe = document.getElementsByTagName('iframe')[0];
                        var iframe_width = iframe.getAttribute('width');
                        var iframe_height = iframe.getAttribute('height');
                        var scale_width = width / iframe_width;
                        var scale_height = height / iframe_height;

                        var scale = Math.min(scale_width, scale_height);
                        var transform_x = -(((width / scale_width) - iframe_width) / 2);
                        var transform_y = -(((height / scale_height) - iframe_height) / 2);
                        iframe.setAttribute('style', 'transform: scale('+scale_width+','+scale_height+'); transform-origin: '+transform_x+'px '+transform_y+'px;-webkit-transform: scale('+scale_width+','+scale_height+'); -webkit-transform-origin: '+transform_x+'px '+transform_y+'px;')
                    }}
                    window.addEventListener('load', resize, true);
                    window.addEventListener('resize', resize, true);
                </script>
            </body>
            </html>""".format(src, width, height)
    iframe_page = 'plugins/embed/iframe_' + file_hash + '.html'
    with open(os.path.join(get_root_path(), 'static', iframe_page), 'w') as f:
        f.write(html)
    return iframe_page


def invalidate_cache(channel_id):
    channel = PluginChannel.get(channel_id)
    file_hash = get_file_hash(channel_id, channel.get_config_param('link'))
    _, full_iframe_path, _, full_inlined_page_path = get_paths(file_hash)

    def safe_rm(path):
        if os.path.exists(path):
            os.remove(path)

    safe_rm(full_iframe_path)
    safe_rm(full_inlined_page_path)


def get_file_hash(channel_id, link):
    return hashlib.md5((str(channel_id) + link).encode()).hexdigest()


def get_paths(file_hash):
    iframe_path = 'plugins/embed/iframe_' + file_hash + '.html'
    file_prefix = os.path.join(get_root_path(), 'static')
    full_iframe_path = os.path.join(file_prefix, iframe_path)
    inlined_page = 'plugins/embed/' + file_hash + '.html'
    full_inlined_page_path = os.path.join(file_prefix, inlined_page)
    return iframe_path, full_iframe_path, inlined_page, full_inlined_page_path


class EmbedCapsule(PluginCapsule):
    def __init__(self, iframe, duration):
        self._slides = [EmbedSlide(iframe, duration)]

    def get_slides(self):
        return self._slides

    def get_theme(self):
        return 'ingi'

    def __repr__(self):
        return str(self.__dict__)


class EmbedSlide(PluginSlide):
    def __init__(self, iframe, duration):
        self._duration = duration
        self._content = {'background-1': {'iframe': iframe}}

    def get_duration(self):
        return self._duration

    def get_content(self):
        return self._content

    def get_template(self) -> str:
        return "template-image-bg"

    def __repr__(self):
        return str(self.__dict__)
