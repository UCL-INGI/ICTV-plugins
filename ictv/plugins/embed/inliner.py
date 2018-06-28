#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# vim:tabstop=4:expandtab:sw=4:softtabstop=4
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

import base64
import mimetypes
import re
import urllib
import sys
from bs4 import BeautifulSoup


def inline(url, output_filename, logger, scripts=None):
    if scripts is None:
        scripts = []

    def is_remote(address):
        return urllib.parse.urlparse(address)[0] in ('http', 'https')

    def data_encode_image(name, content):
        return 'data:%s;base64,%s' % (mimetypes.guess_type(name)[0], base64.standard_b64encode(content).decode("utf-8"))

    def ignore_url(address):
        url_blacklist = ('getsatisfaction.com',
                         'google-analytics.com',)

        for bli in url_blacklist:
            if address.find(bli) != -1:
                return True

        return False

    def get_content(from_, expect_binary=False):
        if is_remote(from_):
            if ignore_url(from_):
                return ''

            with urllib.request.urlopen(from_) as f:
                data = f.read()
            if expect_binary:
                return data
            else:
                return data.decode("utf-8")
        else:
            with open(from_, "rb" if expect_binary else "r") as f:
                return f.read()

    def resolve_path(base, target):
        if True:
            return urllib.parse.urljoin(base, target)

        if is_remote(target):
            return target

        if target.startswith('/'):
            if is_remote(base):
                protocol, rest = base.split('://')
                return '%s://%s%s' % (protocol, rest.split('/')[0], target)
            else:
                return target
        else:
            try:
                base, rest = base.rsplit('/', 1)
                return '%s/%s' % (base, target)
            except ValueError:
                return target

    def replace_javascript(base_url, soup):
        for js in soup.find_all('script', {'src': re.compile('.+')}):
            try:
                real_js = get_content(resolve_path(base_url, js['src']))
                new_tag = soup.new_tag('script')
                new_tag.string = real_js
                js.replace_with(new_tag)
            except Exception as e:
                logger.info('Failed to load javascript from %s' % js['src'])
                logger.info(e)

    css_url = re.compile(r'url\((.+)\)')

    def replace_css(base_url, soup):
        for css in soup.findAll('link', {'rel': 'stylesheet', 'href': re.compile('.+')}):
            try:
                real_css = get_content(resolve_path(base_url, css['href']))

                def replacer(result):
                    try:
                        path = resolve_path(resolve_path(base_url, css['href']), result.groups()[0])
                        return 'url(%s)' % data_encode_image(path, get_content(path, True))
                    except Exception as e:
                        logger.debug('Failed to encode css for path %s' % path)
                        logger.debug(e)
                        return ''

                new_tag = soup.new_tag('style')
                new_tag.string = re.sub(css_url, replacer, real_css)
                css.replaceWith(new_tag)

            except Exception as e:
                logger.info('Failed to load css from %s' % css['href'])
                logger.info(e)

    def replace_images(base_url, soup):
        from itertools import chain

        for img in chain(soup.findAll('img', {'src': re.compile('.+')}),
                         soup.findAll('input', {'type': 'image', 'src': re.compile('.+')})):
            try:
                path = resolve_path(base_url, img['src'])
                real_img = get_content(path, True)
                img['src'] = data_encode_image(path.lower(), real_img)
            except Exception as e:
                logger.info('Failed to load image from %s' % img['src'])
                logger.info(e)

    def replace_backgrounds(base_url, soup):
        for e in soup.find_all(style=lambda x: x and 'background-image' in x):
            new_style = []
            try:
                for property, value in [(p.strip(), v.strip()) for (p, v) in
                                        [x.strip().split(':') for x in e['style'].strip().split(';') if len(x) > 0]]:
                    if (
                            property == 'background-image' or property == 'background') and 'url(' in value and not 'url(data' in value:
                        url = value[value.find("(") + 1:value.find(")")]
                        path = resolve_path(base_url, url)
                        img = data_encode_image(path.lower(), get_content(path, True))
                        new_style.append((property, value.replace(url, img)))
                    else:
                        new_style.append((property, value))
                e['style'] = '; '.join(property + ': ' + value for property, value in new_style)
            except Exception as e:
                logger.info('Failed to load background-image from %s' % e['style'])
                logger.info(e)

    soup = BeautifulSoup(get_content(url), 'lxml')

    replace_javascript(url, soup)
    replace_css(url, soup)
    replace_images(url, soup)
    replace_backgrounds(url, soup)

    for script in scripts:
        script_tag = soup.new_tag('script')
        script_tag['src'] = script
        soup.head.append(script_tag)

    prevent_error_script = soup.new_tag('script')
    prevent_error_script.string = "window.onerror = function(e) {console.log(e); return true;};"
    soup.body.insert(0, prevent_error_script)

    with open(output_filename, 'wb') as res:
        res.write(str(soup).encode("utf-8"))


if __name__ == '__main__':
    inline(sys.argv[1], sys.argv[2])
