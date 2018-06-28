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

from urllib.parse import urlparse

from pyquery import PyQuery

from ictv.models.channel import PluginChannel
from ictv.plugin_manager.plugin_capsule import PluginCapsule
from ictv.plugin_manager.plugin_manager import get_logger
from ictv.plugin_manager.plugin_slide import PluginSlide
from ictv.plugin_manager.plugin_utils import MisconfiguredParameters


def get_content(channel_id):
    channel = PluginChannel.get(channel_id)
    logger_extra = {'channel_name': channel.name, 'channel_id': channel.id}
    logger = get_logger('img-grabber', channel)
    url = channel.get_config_param('url')
    image_selector = channel.get_config_param('image_selector')
    attr = channel.get_config_param('src_attr')
    qrcode = channel.get_config_param('qrcode')
    if not url or not image_selector or not attr:
        logger.warning('Some of the required parameters are empty', extra=logger_extra)
        return []
    try:
        doc = PyQuery(url=url)
    except Exception as e:
        raise MisconfiguredParameters('url', url, 'The following error was encountered: %s.' % str(e))
    img = doc(image_selector).eq(0).attr(attr)
    if not img:
        message = 'Could not find img with CSS selector %s and attribute %s' % (image_selector, attr)
        raise MisconfiguredParameters('image_selector', image_selector, message).add_faulty_parameter('src_attr', attr, message)
    if img[:4] != 'http' and img[:4] != 'ftp:':
        img = '{uri.scheme}://{uri.netloc}/'.format(uri=urlparse(url)) + img
    duration = channel.get_config_param('duration') * 1000
    text = doc(channel.get_config_param('text_selector')).eq(0).text()
    alternative_text = channel.get_config_param('alternative_text')
    return [ImgGrabberCapsule(img, text if text else alternative_text, duration, qrcode=url if qrcode else None)]


class ImgGrabberCapsule(PluginCapsule):
    def __init__(self, img_src, text, duration, qrcode=None):
        self._slides = [ImgGrabberSlide(img_src, text, duration, qrcode)]

    def get_slides(self):
        return self._slides

    def get_theme(self):
        return None

    def __repr__(self):
        return str(self.__dict__)


class ImgGrabberSlide(PluginSlide):
    def __init__(self, img_src, text, duration, qrcode):
        self._duration = duration
        self._content = {'background-1': {'src': img_src, 'size': 'contain'}, 'text-1': {'text': text}}
        if qrcode:
            self._content['image-1'] = {'qrcode': qrcode}
        self._has_qr_code = qrcode is not None

    def get_duration(self):
        return self._duration

    def get_content(self):
        return self._content

    def get_template(self) -> str:
        return 'template-background-text-qr'

    def __repr__(self):
        return str(self.__dict__)
