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

import copy
import ipaddress
import json
import os
from collections import OrderedDict
from functools import partial

import web
from ictv.plugin_manager.plugin_slide import PluginSlide

from ictv.storage.storage_manager import StorageManager
from sqlobject import SQLObjectNotFound

from ictv.common import get_root_path
from ictv.models.role import UserPermissions
from ictv.models.user import User
from ictv.app import sidebar
from ictv.common.feedbacks import get_feedbacks, get_next_feedbacks, pop_previous_form
from ictv.common.utils import deep_update
from ictv.libs.html import HTML
from ictv.pages.utils import ICTVAuthPage, ICTVPage
from ictv.plugin_manager.plugin_capsule import PluginCapsule
from ictv.plugin_manager.plugin_manager import PluginManager
from ictv.plugin_manager.plugin_utils import ChannelGate, seeother
from ictv.plugins.editor.editor import EditorSlide, EditorCapsule, AssetSlideMapping
from ictv.renderer.renderer import SlideRenderer, Themes, Templates

from web.contrib.template import render_jinja


def get_app(ictv_app):
    """ Returns the web.py application of the editor. """

    urls = (
        'index', 'ictv.plugins.editor.capsules_page.CapsulesPage',
        'template/(\d+)/(.+)', 'ictv.plugins.editor.app.ServeTemplate',
        'capsules', 'ictv.plugins.editor.capsules_page.CapsulesPage',
        'capsules/(\d+)', 'ictv.plugins.editor.slides_page.SlidesPage',
        'capsules/(\d+)/newslide', 'ictv.plugins.editor.app.Index',
        'edit/(\d+)', 'ictv.plugins.editor.app.Edit',
        'preview/expired', 'ictv.plugins.editor.rendering_pages.RenderExpired',
        'preview/currentandfuture', 'ictv.plugins.editor.rendering_pages.RenderCurrentAndFuture',
        'render/(\d+)/(\d+)?/?(.*)', 'ictv.plugins.editor.app.LocalSlideRender',
        'api/capsules', 'ictv.plugins.editor.api.APIIndex',
        'api/capsules/(\d+)', 'ictv.plugins.editor.api.APICapsules',
        'api/capsules/(\d+)/slides', 'ictv.plugins.editor.api.APIIndexSlides',
        'api/capsules/(\d+)/slides/(\d+)', 'ictv.plugins.editor.api.APISlides',
        'api/templates', 'ictv.plugins.editor.api.APITemplates',
    )

    app = web.application(urls, globals())
### OLD ###
#    app.renderer = web.template.render(os.path.join(os.path.dirname(__file__), 'templates'),
#                                       base=os.path.join(get_root_path(), 'templates', 'base'),
#                                       globals={'session': ictv_app.session,
#                                                'get_feedbacks': get_feedbacks, 'get_next_feedbacks': get_next_feedbacks,
#                                                'pop_previous_form': pop_previous_form, 'json': json,
#                                                'UserPermissions': UserPermissions,
#                                                'str': str, 'sidebar_collapse': True, 'show_header': False,
#                                                'show_footer': False, 'User': User},
#                                       cache=not ictv_app.config['debug']['debug_on_error'])
#

### Jinja2 ###
    template_globals = {'session': ictv_app.session,
             'get_feedbacks': get_feedbacks, 'get_next_feedbacks': get_next_feedbacks,
             'pop_previous_form': pop_previous_form, 'json': json,
             'UserPermissions': UserPermissions,
             'str': str, 'sidebar_collapse': True, 'show_header': False,
             'show_footer': False, 'User': User,'base':'base.html'}
    app.renderer = render_jinja([os.path.join(os.path.dirname(__file__), 'templates/'),os.path.join(get_root_path(), 'templates/')])
    app.renderer._lookup.globals.update(**template_globals)


    def get_templates():
        """ Returns a list of templates usable by the editor. """
        templates = OrderedDict()

        for template in Templates:
            templates[template] = {'themes': {}, 'name': Templates[template]['name'],
                                   'description': Templates[template]['description']}
            for theme in Themes:
                image_filename = '%s-%s.png' % (template, theme)
                if os.path.isfile(os.path.join(get_root_path(), 'plugins/editor/static/images', image_filename)):
                    templates[template]['themes'][theme] = image_filename
                else:
                    templates[template]['themes'][theme] = 'placeholder_template.png'
        return templates

    def get_editor_slide_renderer():
        """ Returns an editor slide renderer. """
        def make_title(**kwargs):
            h = HTML()
            try:
                args = {'id': 'title-' + str(kwargs['number']), 'klass': 'title', 'data-editor-type': "text",
                        'data-editor-placeholder': kwargs['editor_placeholder'],
                        'data-editor-label': kwargs['editor_label'], 'data-editor-default': kwargs['editor_default']}
            except KeyError:
                args = {'id': 'title-' + str(kwargs['number']), 'klass': 'title', 'data-editor-type': "text",
                        'data-editor-placeholder': 'Title',
                        'data-editor-label': 'Title', 'data-editor-default': 'Title'}
            if kwargs['content'] is not None:
                text = kwargs['content']['title-' + str(kwargs['number'])]['text']
                args['data-editor-default'] = text
            if 'max_chars' in kwargs:
                args['data-editor-max-chars'] = str(kwargs['max_chars'])
            h.h1('', **args)
            return str(h)

        def make_subtitle(**kwargs):
            h = HTML()
            try:
                args = {'id': 'subtitle-' + str(kwargs['number']), 'klass': 'subtitle', 'data-editor-type': "text",
                        'data-editor-placeholder': kwargs['editor_placeholder'],
                        'data-editor-label': kwargs['editor_label'], 'data-editor-default': kwargs['editor_default'],
                        'data-editor-optional': "true"}
            except KeyError:
                args = {'id': 'subtitle-' + str(kwargs['number']), 'klass': 'subtitle', 'data-editor-type': "text",
                        'data-editor-placeholder': 'Subtitle', 'data-editor-label': 'Subtitle',
                        'data-editor-default': 'Subtitle', 'data-editor-optional': "true"}
            if kwargs['content'] is not None:
                text = kwargs['content']['subtitle-' + str(kwargs['number'])]['text']
                args['data-editor-default'] = text
            if 'max_chars' in kwargs:
                args['data-editor-max-chars'] = str(kwargs['max_chars'])
            h.h4('', **args)
            return str(h)

        def make_img(**kwargs):
            h = HTML()
            try:
                args = {'id': 'image-' + str(kwargs['number']), 'klass': 'sub-image', 'data-editor-type': "image",
                        'data-editor-placeholder': kwargs['editor_placeholder'],
                        'data-editor-label': kwargs['editor_label'], 'data-editor-default': kwargs['editor_default'],
                        'data-editor-mediatype': "image"}
            except KeyError:
                args = {'id': 'image-' + str(kwargs['number']), 'klass': 'sub-image', 'data-editor-type': "image",
                        'data-editor-placeholder': "/static/plugins/editor/placeholders/270x350.png",
                        'data-editor-label': 'Image',
                        'data-editor-default': "/static/plugins/editor/placeholders/270x350.png",
                        'data-editor-mediatype': "image"}
            if kwargs['content'] is not None:
                src = kwargs['content']['image-' + str(kwargs['number'])]['src']
                args['data-editor-default'] = src
            if 'style' in kwargs:
                args['style'] = kwargs['style']
            h.img(src='/static/plugins/editor/placeholders/270x350.png', **args)
            return str(h)

        def make_logo(**kwargs):
            h = HTML()
            try:
                args = {'id': 'logo-' + str(kwargs['number']), 'data-editor-type': "image",
                        'data-editor-placeholder': kwargs['editor_placeholder'],
                        'data-editor-label': kwargs['editor_label'], 'data-editor-default': kwargs['editor_default'],
                        'data-editor-mediatype': "image"}
            except KeyError:
                args = {'id': 'logo-' + str(kwargs['number']), 'data-editor-type': "image",
                        'data-editor-placeholder': "/static/plugins/editor/placeholders/270x350.png",
                        'data-editor-label': 'Logo',
                        'data-editor-default': "/static/plugins/editor/placeholders/270x350.png",
                        'data-editor-mediatype': "image"}
            if kwargs['content'] is not None:
                src = kwargs['content']['logo-' + str(kwargs['number'])]['src']
                args['data-editor-default'] = src
            h.img(src=args['data-editor-default'], **args)
            return str(h)

        def make_text(**kwargs):
            h = HTML()
            try:
                args = {'id': 'text-' + str(kwargs['number']), 'data-editor-type': "textarea",
                        'data-editor-placeholder': kwargs['editor_placeholder'],
                        'data-editor-label': kwargs['editor_label'], 'data-editor-default': kwargs['editor_default'],
                        'style': kwargs.get('style') or 'text-align:justify', 'klass': 'text'}
            except KeyError:
                args = {'id': 'text-' + str(kwargs['number']), 'data-editor-type': "textarea",
                        'data-editor-placeholder': "Text", 'data-editor-label': 'Text',
                        'data-editor-default': "Text", 'style': kwargs.get('style') or 'text-align:justify', 'klass': 'text'}
            if kwargs['content'] is not None:
                text = kwargs['content']['text-' + str(kwargs['number'])]['text']
                args = args['data-editor-default'] = text
            if 'max_chars' in kwargs:
                args['data-editor-max-chars'] = str(kwargs['max_chars'])
            h.div('', **args)
            return str(h)

        def make_background(**kwargs):
            if kwargs['content'] is None:
                src = kwargs['editor_default']
                size = 'cover'
                color = 'black'
            else:
                id = 'background-' + str(kwargs['number'])
                src = kwargs['content'][id]['src']
                size = kwargs['content'][id]['size']
                color = kwargs['content'][id]['color'] if 'color' in kwargs['content'][id] else 'black'
            src = '/static/plugins/editor/%s' % src if not src.startswith('/static/plugins/editor/') else src
            return 'data-background-image="' + src + '" data-background-size="' + size + '" data-background-color="' + color + '" ' \
                                                                                         'data-editor-type="background" ' \
                                                                                         'data-editor-placeholder="/static/plugins/editor/images/beach.jpg"' \
                                                                                         'data-editor-default="' + src + '"' \
                                                                                         'data-editor-label="Arrière-plan"'

        renderer_globals = {
            'title': make_title,
            'subtitle': make_subtitle,
            'img': make_img,
            'logo': make_logo,
            'text': make_text,
            'background': make_background
        }

        return SlideRenderer(renderer_globals=renderer_globals, app=ictv_app)

    app.slide_templates = get_templates()
    app.slide_renderer = get_editor_slide_renderer()

    EditorPage.plugin_app = app

    return app


class EditorPage(ICTVAuthPage):
    plugin_app = None

    @property
    def editor_app(self):
        """ Returns the web.py application singleton of the editor. """
        return EditorPage.plugin_app

    @property
    def renderer(self):
        """ Returns the webapp renderer. """
        return self.editor_app.renderer

    @property
    def slide_renderer(self) -> SlideRenderer:
        """ Returns the slide renderer of the editor. """
        return self.editor_app.slide_renderer

    @property
    def slide_templates(self) -> dict:
        """ Returns the templates usable by the editor. """
        return self.editor_app.slide_templates


class Index(EditorPage):
    @ChannelGate.contributor
    @sidebar
    def GET(self, capsuleid, channel):
        try:
            capsule = EditorCapsule.get(capsuleid)
            if capsule.channel != channel:
                return 'there is no capsule with id ' + capsuleid + ' in channel ' + channel.name
        except SQLObjectNotFound:
            return 'there is no capsule with id ' + capsuleid
        capsule_theme = capsule.get_theme() if capsule.get_theme() in Themes else self.app.config['default_theme']
        vertical = channel.get_config_param('vertical')
        templates = self.slide_templates
        template = channel.get_config_param('default_template')
        if vertical:
            templates = {'template-image-bg': templates['template-image-bg'],
                         'template-background-text-center': self.slide_templates['template-background-text-center']}
            default_template = channel.get_config_param('default_template')
            template = template if default_template in ["template-image-bg", 'template-background-text-center'] else 'template-background-text-center'
        return self.renderer.editor(capsule=capsule, channel=channel, slide=None,
                                    old_content=Themes.get_slide_defaults(capsule_theme),
                                    template=template,
                                    templates=templates,
                                    theme=capsule_theme,
                                    theme_palette=Themes[capsule_theme].get('ckeditor_palette'),
                                    themes=Themes.prepare_for_css_inclusion([capsule_theme]),
                                    theme_defaults=json.dumps(Themes.get_slide_defaults(capsule_theme)),
                                    vertical=vertical)

    @ChannelGate.contributor
    def POST(self, capsuleid, channel):
        form = web.input()
        content, assets = update_slide(form=form, storage_manager=StorageManager(channel.id), user_id=self.session['user']['id'])
        template = form['template']
        try:
            capsule = EditorCapsule.get(capsuleid)
            if capsule.channel != channel:
                return 'there is no capsule with id ' + capsuleid + ' in channel ' + channel.name
        except SQLObjectNotFound:
            return 'there is no capsule with id ' + capsuleid
        s = EditorSlide(duration=-1, content=content,
                        s_order=EditorSlide.selectBy(capsule=capsuleid).count(), template=template, capsule=capsuleid)
        list(capsule.slides).append(s)
        for asset in assets:
            mapping = AssetSlideMapping(assetID=asset.id, slideID=s.id)
        raise seeother(channel.id, '/capsules/' + str(capsuleid))


class Edit(EditorPage):
    @ChannelGate.contributor
    @sidebar
    def GET(self, slide_id, channel):
        try:
            slide_id = int(slide_id)
            s = EditorSlide.get(slide_id)
            if s.contains_video:
                raise seeother(channel.id, '/capsules/%d' % s.capsule.id)
            plugin_s = s.to_plugin_slide()
        except ValueError:
            return "this is not a valid slide id"
        except SQLObjectNotFound:
            return "there is no slide with the id " + str(slide_id) + " in the channel " + str(channel.id)
        capsule = s.capsule.to_plugin_capsule()
        PluginManager.dereference_assets([capsule])
        capsule_theme = capsule.get_theme() if capsule.get_theme() in Themes else self.app.config['default_theme']
        content = Themes.get_slide_defaults(capsule_theme)
        deep_update(content, s.get_content())
        vertical = channel.get_config_param('vertical')
        templates = self.slide_templates
        template = s.get_template()
        if vertical:
            templates = {'template-image-bg': templates['template-image-bg'],
                         'template-background-text-center': self.slide_templates['template-background-text-center']}
            default_template = channel.get_config_param('default_template')
            template = template if default_template in ["template-image-bg", 'template-background-text-center'] else 'template-background-text-center'
        return self.renderer.editor(capsule=s.capsule, channel=channel, slide=s, template=template,
                                    old_content=json.dumps(content), templates=templates,
                                    theme=capsule_theme,
                                    theme_palette=Themes[capsule_theme].get('ckeditor_palette'),
                                    themes=Themes.prepare_for_css_inclusion([capsule_theme]),
                                    theme_defaults=json.dumps(Themes.get_slide_defaults(capsule_theme)),
                                    vertical=channel.get_config_param('vertical'))

    @ChannelGate.contributor
    def POST(self, slide_id, channel):
        try:
            s_db = EditorSlide.get(int(slide_id))
        except ValueError:
            return "this is not a valid slide id"
        except SQLObjectNotFound:
            return "there is no slide with the id " + str(slide_id) + " in the channel " + str(channel.id)
        form = web.input()
        new_content, assets = update_slide(form=form, storage_manager=StorageManager(channel.id), user_id=self.session['user']['id'])
        template = form['template']
        previous_content = copy.deepcopy(s_db.content)
        for field_type, input_data in previous_content.items():
            if 'file' in input_data and new_content[field_type].pop('src', None):
                # New content is a link to the previous asset, keep the asset reference
                new_content[field_type]['file'] = input_data['file']
            if 'file' in input_data and 'file' in new_content[field_type] and input_data['file'] != new_content[field_type]['file']:
                AssetSlideMapping.selectBy(assetID=input_data['file'], slideID=s_db.id).getOne().destroySelf()
        for asset in assets:
            mapping = AssetSlideMapping(assetID=asset.id, slideID=s_db.id)
        s_db.template = template
        s_db.content = new_content  # Force SQLObject update
        raise seeother(channel.id, '/capsules/' + str(s_db.capsule.id))


def update_slide(form, storage_manager, user_id):
    content = {}
    assets = []
    for key, value in form.items():
        if key == 'background-image':
            key = 'background-1'  # Rename to renderer naming convention
        if key.startswith("title-") or key.startswith("subtitle-") or key.startswith("text-"):
            content[key] = {'text': str(value)}
        elif key.startswith("logo-") or key.startswith("image-") or key.startswith("background-") and not (key.endswith("-cover") or key.endswith("-color")):
            # when there is an image input
            filename_key = 'filename-' + key
            if value == b'':
                # Asset already exists
                if (not form[filename_key].startswith('/static/themes/') and \
                   not form[filename_key].startswith('/static/plugins/editor')) or \
                   key.startswith("background-"): # Prevent setting a default value coming from the theme as real content.
                    content[key] = {'src': form[filename_key]}
            else:
                asset = storage_manager.store_file(value, form[filename_key], user=user_id)
                assets.append(asset)
                content[key] = {'file': asset.id}
            if key.startswith('background-'):
                content[key]['size'] = 'cover' if 'background-1-cover' in form and form['background-1-cover'] == 'on' else 'contain'
                content[key]['color'] = 'white' if 'background-1-color' in form and form['background-1-color'] == 'on' else 'black'
    return content, assets


class ServeTemplate(EditorPage):
    def GET(self, capsuleid, template_name):
        if template_name not in self.slide_templates:
            return 'no such template : "' + template_name + '"'
        else:
            try:
                capsule = EditorCapsule.get(int(capsuleid))
            except ValueError:
                return 'This is not a valid capsule id'
            except SQLObjectNotFound:
                return 'There is no capsule with id ' + capsuleid
            return self.slide_renderer.render_template(template_name=template_name, content=None,
                                                       theme_name=capsule.theme if capsule.theme in Themes else self.config['default_theme'])


class LocalSlideRender(EditorPage):  # TODO: This is not secure
    def GET(self, capsule_id, slide_id=None, template=None):
        capsule = EditorCapsule.get(capsule_id)
        theme = capsule.theme if capsule.theme in Themes else self.config['default_theme']
        if slide_id:
            slide = EditorSlide.get(slide_id)

            capsule = type('DummyCapsule', (PluginCapsule, object), {'get_slides': lambda: [slide],
                                                                     'get_theme': lambda: theme})
            self.plugin_manager.dereference_assets([capsule])

            content = slide.get_content()
            duration = slide.duration
            t = template if template else slide.get_template()
            slide = type('DummySlide', (PluginSlide, object), {'get_duration': lambda: duration,
                                                               'get_content': lambda: content,
                                                               'get_template': lambda: t})
        else:
            slide = type('DummySlide', (PluginSlide, object), {'get_duration': lambda: 5000,
                                                               'get_content': lambda: {},
                                                               'get_template': lambda: template})

        if template:
            content = self.get_slide_defaults(slide)
            deep_update(content, Themes.get_slide_defaults(theme))
            deep_update(content, slide.get_content())
            slide.get_content = lambda: content

        return self.ictv_renderer.preview_slide(slide, theme, small_size=True)

    def get_slide_defaults(self, slide):
        """ Returns the default values of slide elements based on the given template """

        slide_defaults = {}

        def set_value(field_type, **kwargs):
            element_id = field_type + '-' + str(kwargs['number'])
            if field_type in ('title', 'subtitle', 'text'):
                slide_defaults[element_id] = {'text': kwargs.get('editor_default')}
            elif field_type in ('img', 'logo', 'background'):
                slide_defaults[element_id] = {'src': kwargs.get('editor_default')}
                if field_type == 'background':
                    slide_defaults[element_id]['size'] = 'cover'
                    slide_defaults[element_id]['color'] = 'black'

        renderer_globals = {
            field_type: partial(set_value, field_type=field_type)
            for field_type in ('title', 'subtitle', 'text', 'img', 'logo', 'background')
        }
        SlideRenderer(renderer_globals=renderer_globals, app=self).render_slide(slide)

        return slide_defaults
