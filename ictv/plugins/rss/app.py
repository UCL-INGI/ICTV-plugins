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
import traceback
from urllib.parse import urlparse

import builtins
import web

from ictv.common import get_root_path
from ictv.models.role import UserPermissions
from ictv.models.user import User
from ictv.app import sidebar
from ictv.common.feedbacks import get_feedbacks, get_next_feedbacks, pop_previous_form
from ictv.common.json_datetime import DateTimeEncoder
from ictv.pages.channel_page import ChannelPage
from ictv.pages.utils import ICTVPage
from ictv.plugin_manager.plugin_utils import ChannelGate
from ictv.plugins.rss.rss import feedparser_parse, get_content
from ictv.renderer.renderer import Templates

from web.contrib.template import render_jinja

urls = (
    'index', 'ictv.plugins.rss.app.IndexPage',
    'feed', 'ictv.plugins.rss.app.FeedGetter',
    'content', 'ictv.plugins.rss.app.ContentPage',
    'preview', 'ictv.plugins.rss.app.PreviewPage'
)


def get_app(ictv_app):
    app = web.application(urls, globals())
    template_globals = {'session': ictv_app.session,
             'get_feedbacks': get_feedbacks,
             'get_next_feedbacks': get_next_feedbacks,
             'pop_previous_form': pop_previous_form,
             'UserPermissions': UserPermissions,
             'str': str, 'sidebar_collapse': True, 'show_header': False,
             'show_footer': False, 'User': User,'base':'base.html'}
    app.renderer = render_jinja([os.path.join(os.path.dirname(__file__), 'templates/'),os.path.join(get_root_path(), 'templates/')])
    app.renderer._lookup.globals.update(**template_globals)

    RssPage.plugin_app = app

    return app


class RssPage(ICTVPage):
    plugin_app = None

    @property
    def rss_renderer(self):
        return RssPage.plugin_app.renderer

    @property
    def rss_app(self):
        """ Returns the web.py application singleton of the editor. """
        return RssPage.plugin_app


class IndexPage(RssPage):
    @ChannelGate.contributor
    @sidebar
    def GET(self, channel):
        current_user = User.get(self.session['user']['id'])
        readable_params, writable_params = ChannelPage.get_params(channel, current_user)

        rss = '<\s*div\s+class\s*=\s*\"\s*box-body\s*\"\s*>((.|\n)*)<\s*hr\s*\/>\s*<\s*\/div\s*>\s*<\s*div\s+class\s*=\s*\"\s*box-footer\s*\"\s*>'
        config_page = self.renderer.channel(
                channel=channel,
                templates=sorted([(template, Templates[template]['name']) for template in Templates]),
                readable_params=readable_params,
                writable_params=writable_params,
                can_modify_cache=False,
                can_modify_capsule_filter=False,
                pattern=re.compile(r"list\[.*\]")
            )

        config_page = re.findall(rss, str(config_page))[0][0]

        return self.rss_renderer.index(
            channel=channel,
            config_content=config_page
        )


class FeedGetter(RssPage):
    @ChannelGate.contributor
    def POST(self, channel):
        url = web.data().decode()
        if FeedGetter._is_url(url):
            web.header('Content-Type', 'application/json')
            try:
                return json.dumps(feedparser_parse(url).entries, cls=DateTimeEncoder)
            except TypeError:
                return "Feed could not be parsed"
        raise web.notfound()

    @staticmethod
    def _is_url(url):
        o = urlparse(url)
        return o.scheme != '' or o.netloc != ''


def post_process_config(config, channel):
    for k, v in list(config.items()):
        if k in channel.plugin.channels_params:
            value_type = channel.plugin.channels_params[k]['type']
            if value_type in vars(builtins):
                config[k] = vars(builtins)[value_type](v)
        else:
            del config[k]


class ContentPage(RssPage):
    @ChannelGate.contributor
    def POST(self, channel):
        config = json.loads(web.data().decode())
        post_process_config(config, channel)

        capsules = []
        try:
            for c in get_content(channel.id, config):
                slides = []
                for s in c.get_slides():
                    slides.append(s.get_content())
                capsules.append(slides)
        except ValueError:
            return json.dumps(traceback.format_exc())
        return json.dumps(capsules)


class PreviewPage(RssPage):
    @ChannelGate.contributor
    def POST(self, channel):
        config = json.loads(web.input().config)
        post_process_config(config, channel)
        try:
            content = get_content(channel.id, config)
        except ValueError:
            return web.badrequest()

        self.plugin_manager.dereference_assets(content)
        self.plugin_manager.cache_assets(content, channel.id)
        try:
            preview = self.ictv_renderer.render_screen(content, controls=True)
        except (KeyError, ValueError):
            return "Preview could not be generated.<br><code>%s</code>" % traceback.format_exc()
        except(TypeError):
            return "A problem occured."
        return preview
