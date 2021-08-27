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

import datetime
import json
from json import JSONDecodeError

from sqlobject import SQLObjectNotFound
from sqlobject.dberrors import DuplicateEntryError
from wand.color import Color
from wand.image import Image

from ictv.app import sidebar
from ictv.common.feedbacks import add_feedback, ImmediateFeedback, store_form
from ictv.plugin_manager.plugin_manager import get_logger
from ictv.plugin_manager.plugin_utils import ChannelGate, seeother
from ictv.plugins.editor.app import EditorPage
from ictv.plugins.editor.editor import EditorCapsule, EditorSlide, AssetSlideMapping
from ictv.renderer.renderer import Themes
from ictv.storage.storage_manager import StorageManager

import flask
import ictv.flask.response as resp

class SlidesPage(EditorPage):
    @ChannelGate.contributor
    def get(self, capsuleid, channel):
        try:
            caps_db = EditorCapsule.get(int(capsuleid))
            if caps_db.channel != channel:
                return "there is no capsule with the id " + str(capsuleid) + " in the channel " + str(channel.id)
        except ValueError:
            return "this is not a valid capsule id"
        except SQLObjectNotFound:
            return "there is no capsule with the id " + str(capsuleid) + " in the channel " + str(channel.id)
        slides = EditorSlide.rectify_s_order(capsuleid)
        return self.render_page(channel=channel, capsule=caps_db, slides=slides)

    @ChannelGate.contributor
    def post(self, capsuleid, channel):
        try:
            caps_db = EditorCapsule.get(int(capsuleid))
            slides = caps_db.slides
            form = self.form

            logger_extra = {'channel_name': channel.name, 'channel_id': channel.id}
            logger = get_logger('editor', channel)
            if caps_db.channel != channel:
                return "there is no capsule with the id " + str(capsuleid) + " in the channel " + str(channel.id)
            if form.action == 'delete':
                try:
                    slide = EditorSlide.get(int(form.id))
                except ValueError:
                    return "this is not a valid slide id"
                except SQLObjectNotFound:
                    return "there is no slide with the id " + form.id + " in the channel " + str(channel.id)
                slide.destroySelf()
                slides = EditorSlide.rectify_s_order(capsuleid)
            elif form.action == 'duplicate':
                try:
                    slide = EditorSlide.get(int(form.id))
                except ValueError:
                    return "this is not a valid slide id"
                except SQLObjectNotFound:
                    return "there is no slide with the id " + form.id + " in the channel " + str(channel.id)
                duplicate = slide.duplicate(s_order=-1)
                caps_db.insert_slide_at(duplicate, slide.s_order + 1)
                slides = caps_db.slides
            elif form.action == 'order':
                try:
                    new_order = json.loads(form.order)
                except AttributeError:
                    return "you seem to try to change the order of slides that doesn't exist..."
                except JSONDecodeError:
                    return "invalid changes"
                for k, v in new_order.items():
                    try:
                        slide = EditorSlide.get(int(k))
                        if slide.capsule.id != int(capsuleid):
                            return "you try to change the order of a slide in a different capsule..."
                        slide.s_order = int(v)
                    except ValueError:
                        return "invalid changes"
                    except SQLObjectNotFound:
                        return "You try to change the order of slides that doesn't exist..."
                slides = EditorSlide.rectify_s_order(capsuleid)
            elif form.action == 'theme':
                caps_db = EditorCapsule.get(int(capsuleid))
                if caps_db.channel != channel:
                    return "there is no capsule with the id " + str(capsuleid) + " in the channel " + str(channel.id)

                if form.theme not in Themes:
                    raise ImmediateFeedback(form.action, 'not_existing_theme')
                caps_db.theme = form.theme
            elif form.action == 'edit':
                try:
                    name = form.name.strip()
                    capsule = caps_db
                    if not name:
                        raise ValueError('name')

                    date_from = datetime.datetime.strptime(form['date-from'], "%Y-%m-%dT%H:%M:%S%z")
                    date_to = datetime.datetime.strptime(form['date-to'], "%Y-%m-%dT%H:%M:%S%z")
                    if date_to <= date_from:
                        raise ValueError('dates')

                    capsule.name = name
                    capsule.validity_from = date_from
                    capsule.validity_to = date_to
                except SQLObjectNotFound:
                    return seeother(channel.id, '/')
                except DuplicateEntryError:
                    raise ImmediateFeedback(form.action, 'name_already_exists')
                except ValueError as e:
                    raise ImmediateFeedback(form.action, 'invalid_name' if e.args[0] == 'name' else 'dates_inverted')
            elif form.action.startswith('import'):
                storage_manager = StorageManager(channel.id)
                capsule = caps_db
                background_color = 'white' if 'white-background' in form and form['white-background'] == 'on' else 'black'
                offset = EditorSlide.selectBy(capsule=capsule).max('s_order')
                offset = offset + 1 if offset is not None else 0

                if form.action == 'import-slides' and 'pdf' in form:
                    slide_files = []
                    try:
                        with Color(background_color) as bg:
                            with Image(blob=form.pdf.read(), resolution=150) as pdf:
                                for i, page in enumerate(pdf.sequence):
                                    img_page = Image(image=page)
                                    img_page.background_color = bg
                                    img_page.alpha_channel = False
                                    img_page.format = 'jpeg'
                                    img_page.transform(resize='1920x1080>')
                                    asset = storage_manager.store_file(img_page.make_blob('jpeg'),
                                                                       filename='import-capsule-%d-slide-%d.jpeg' % (capsule.id, offset + i),
                                                                       user=self.session['user']['id'])
                                    slide_files.append(asset)
                        slide_duration = channel.get_config_param('duration') * 1000
                        for i, slide_file in enumerate(slide_files):
                            s = EditorSlide(duration=slide_duration,
                                            content={'background-1': {'file': slide_file.id,
                                                                      'size': 'contain',
                                                                      'color': background_color}},
                                            s_order=offset + i, template='template-image-bg', capsule=capsule)

                            AssetSlideMapping(assetID=slide_file.id, slideID=s.id)
                    except (ValueError, TypeError):
                        logger.warning('An Exception has been encountered when importing PDF file:', extra=logger_extra,
                                       exc_info=True)
                elif form.action == 'import-video' and 'video' in form:
                    try:
                        video_slide = EditorSlide.from_video(form.video, storage_manager, self.transcoding_queue, capsule, self.session['user']['id'], background_color)
                        if type(video_slide) is str:  # Video is being transcoded
                            raise ImmediateFeedback(form.action, 'video_transcoding', video_slide)
                    except TypeError as e:
                        raise ImmediateFeedback(form.action, 'invalid_video_format', e.type)
                else:
                    resp.badrequest()
            elif form.action == 'duration':
                try:
                    slide_id = int(form.id)
                    slide = EditorSlide.get(slide_id)
                    if "duration" in form:
                        duration = float(form.duration)*1000
                        if duration < 0:
                            raise ImmediateFeedback(form.action, "negative_slide_duration")
                    else:
                        duration = -1
                    slide.duration = duration
                except SQLObjectNotFound:
                    return seeother(channel.id, '/')
                except ValueError:
                    raise ImmediateFeedback(form.action, 'invalid_slide_duration')
            add_feedback(form.action, 'ok')
        except ValueError:
            return "this is not a valid capsule id"
        except SQLObjectNotFound:
            return "there is no capsule with the id " + str(capsuleid) + " in the channel " + str(channel.id)
        except ImmediateFeedback:
            store_form(form)
        return self.render_page(channel=channel, capsule=caps_db, slides=caps_db.slides)

    @sidebar
    def render_page(self, channel, capsule, slides):
        return self.renderer.slides(channel=channel,
                                    capsule=capsule,
                                    slides=slides,
                                    themes=Themes.get_sorted_themes(),
                                    vertical=channel.get_config_param('vertical'))
