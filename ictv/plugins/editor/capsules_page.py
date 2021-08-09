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

from pymediainfo import MediaInfo
from sqlobject import SQLObjectNotFound
from sqlobject.dberrors import DuplicateEntryError
from wand.color import Color
from wand.image import Image

from ictv.app import sidebar
from ictv.common.feedbacks import add_feedback, ImmediateFeedback, store_form
from ictv.plugin_manager.plugin_manager import get_logger
from ictv.plugin_manager.plugin_utils import ChannelGate, VideoSlide
from ictv.plugins.editor.app import EditorPage
from ictv.plugins.editor.editor import EditorCapsule, EditorSlide, AssetSlideMapping
from ictv.storage.storage_manager import StorageManager

import flask
import ictv.flask.response as resp

class CapsulesPage(EditorPage):
    @ChannelGate.contributor
    def get(self, channel):
        capsules = EditorCapsule.rectify_c_order(channel.id)
        return self.render_page(channel, capsules=capsules)

    @ChannelGate.contributor
    def post(self, channel):
        form = self.form

        logger_extra = {'channel_name': channel.name, 'channel_id': channel.id}
        logger = get_logger('editor', channel)
        capsules = None
        try:
            if form['action'] == 'delete':
                try:
                    capsule_id = int(form['id'])
                except ValueError:
                    raise ImmediateFeedback(form.action, 'invalid_id')
                try:
                    capsule = EditorCapsule.get(capsule_id)
                except SQLObjectNotFound:
                    raise ImmediateFeedback(form.action, 'no_id_matching')

                if channel != capsule.channel:
                    raise ImmediateFeedback(form.action, 'wrong_channel')
                if capsule is None:
                    raise ImmediateFeedback(form.action, 'no_id_matching')
                capsule.destroySelf()
                capsules = EditorCapsule.rectify_c_order(channel.id)

            elif form['action'] == 'duplicate':
                try:
                    capsule_id = int(form['id'])
                except ValueError:
                    raise ImmediateFeedback(form.action, 'invalid_id')
                try:
                    capsule = EditorCapsule.get(capsule_id)
                except SQLObjectNotFound:
                    raise ImmediateFeedback(form.action, 'no_id_matching')

                if channel != capsule.channel:
                    raise ImmediateFeedback(form.action, 'wrong_channel')
                if capsule is None:
                    raise ImmediateFeedback(form.action, 'no_id_matching')
                capsule.duplicate(owner_id=self.session['user']['id'])
                capsules = EditorCapsule.rectify_c_order(channel.id)

            elif form.action == 'order':
                try:
                    new_order = json.loads(form.order)
                except AttributeError:
                    return "you seem to try to change the order of slides that doesn't exist..."
                except JSONDecodeError:
                    return "invalid changes"
                capsules_to_reorder = {}
                for k in new_order.keys():
                    try:
                        capsule = EditorCapsule.get(int(k))
                        capsules_to_reorder[k] = capsule
                        if capsule.channel.id != channel.id:
                            return "you try to change the order of a capsule in a different channel..."
                    except SQLObjectNotFound:
                        return "You try to change the order of slides that doesn't exist..."
                sorted_list = sorted(capsules_to_reorder.values(), key=lambda caps: caps.c_order)
                new_to_old_order = {}
                i = 0
                for elem in sorted_list:
                    new_to_old_order[i] = elem.c_order
                    i += 1
                try:
                    for k, v in new_order.items():
                        capsules_to_reorder[k].c_order = new_to_old_order[int(v)]
                except ValueError:
                    return "invalid changes"
                capsules = EditorCapsule.rectify_c_order(channel.id)

            elif form['action'] == 'create' or form['action'].startswith('import'):
                name = form['name'].strip()
                if not name:
                    raise ImmediateFeedback(form.action, 'invalid_name')
                try:
                    if 'date-from' in form and 'date-to' in form:
                        try:
                            date_from = datetime.datetime.strptime(form['date-from'], "%Y-%m-%dT%H:%M:%S%z")
                            date_to = datetime.datetime.strptime(form['date-to'], "%Y-%m-%dT%H:%M:%S%z")
                        except ValueError:
                            raise ImmediateFeedback(form.action, 'wrong_date_values')
                    else:
                        if 'capsule_validity' in channel.plugin_config:
                            validity = int(channel.plugin_config['capsule_validity'])
                        else:
                            validity = int(channel.plugin.channels_params['capsule_validity']['default'])
                        date_from = datetime.datetime.now()
                        time_delta = datetime.timedelta(hours=validity)
                        date_to = date_from + time_delta
                    if date_to <= date_from:
                        raise ImmediateFeedback(form.action, 'dates_inverted')
                    capsule = EditorCapsule(name=form['name'], channel=channel, ownerID=self.session['user']['id'],
                                            creation_date=datetime.datetime.now(),
                                            c_order=EditorCapsule.select().count(),
                                            validity_from=date_from,
                                            validity_to=date_to)
                    if form.action.startswith('import'):
                        storage_manager = StorageManager(channel.id)
                        background_color = 'white' if 'white-background' in form and form['white-background'] == 'on' else 'black'

                        if form.action == 'import-capsule' and 'pdf' in form:

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
                                            slide_files.append(storage_manager.store_file(img_page.make_blob('jpeg'),
                                                                                          filename='import-capsule-%d-slide-%d.jpeg' % (capsule.id, i),
                                                                                          user=self.session['user']['id']))
                                slide_duration = channel.get_config_param('duration') * 1000
                                for i, slide_file in enumerate(slide_files):
                                    s = EditorSlide(duration=slide_duration,
                                                    content={'background-1': {'file': slide_file.id,
                                                                              'size': 'contain',
                                                                              'color': background_color}},
                                                    s_order=i, template='template-image-bg', capsule=capsule)
                                    AssetSlideMapping(assetID=slide_file.id, slideID=s.id)
                            except (ValueError, TypeError):
                                logger.warning('An Exception has been encountered when importing PDF file:',
                                               extra=logger_extra, exc_info=True)
                        elif form.action == 'import-video' and 'video' in form:
                            try:
                                video_slide = EditorSlide.from_video(form.video, storage_manager, self.transcoding_queue, capsule, self.session['user']['id'], background_color)
                                if type(video_slide) is str:  # Video is being transcoded
                                    raise ImmediateFeedback(form.action, 'video_transcoding', video_slide)
                            except TypeError as e:
                                capsule.destroySelf()
                                raise ImmediateFeedback(form.action, 'invalid_video_format', e.type if hasattr(e, 'type') else None)
                        else:
                            resp.badrequest()

                except DuplicateEntryError:
                    raise ImmediateFeedback(form.action, 'name_already_exists')
            elif form['action'] == 'edit':
                name = form['name'].strip()
                if not name:
                    raise ImmediateFeedback(form.action, 'invalid_name')
                try:
                    capsule_id = int(form['id'])
                except ValueError:
                    raise ImmediateFeedback(form.action, 'invalid_id')
                try:
                    capsule = EditorCapsule.get(capsule_id)
                except SQLObjectNotFound:
                    raise ImmediateFeedback(form.action, 'no_id_matching')

                if channel != capsule.channel:
                    raise ImmediateFeedback(form.action, 'wrong_channel')
                try:
                    capsule.name = name
                except DuplicateEntryError:
                    raise ImmediateFeedback(form.action, 'name_already_exists')
                try:
                    date_from = datetime.datetime.strptime(form['date-from'], "%Y-%m-%dT%H:%M:%S%z")
                    date_to = datetime.datetime.strptime(form['date-to'], "%Y-%m-%dT%H:%M:%S%z")
                except ValueError:
                    raise ImmediateFeedback(form.action, 'wrong_date_values')
                if date_to <= date_from:
                    raise ImmediateFeedback(form.action, 'dates_inverted')
                capsule.validity_from = date_from
                capsule.validity_to = date_to
            add_feedback(form.action, 'ok')
        except ImmediateFeedback:
            pass
        store_form(form)
        return self.render_page(channel, capsules)

    @sidebar
    def render_page(self, channel, capsules=None):
        now = datetime.datetime.now()
        if capsules is None:
            capsules_all = EditorCapsule.selectBy(channel=channel.id)
            capsules = capsules_all.filter(EditorCapsule.q.validity_to > now)
            expired_capsules = capsules_all.filter(EditorCapsule.q.validity_to <= now)
        else:
            capsules_all = capsules
            expired_capsules = capsules_all.filter(EditorCapsule.q.validity_to <= now)
            capsules = capsules_all.filter(EditorCapsule.q.validity_to > now)
        if 'capsule_validity' in channel.plugin_config:
            validity = int(channel.plugin_config['capsule_validity'])
        else:
            validity = int(channel.plugin.channels_params['capsule_validity']['default'])
        vertical = channel.get_config_param('vertical')
        default_from = datetime.datetime.now()
        time_delta = datetime.timedelta(hours=validity)
        default_to = default_from + time_delta

        def get_data_edit_object(capsule):
            object = {'id': capsule.id, 'name': capsule.name}
            object['from'] = capsule.validity_from.replace(microsecond=0).isoformat()
            object['to'] = capsule.validity_to.replace(microsecond=0).isoformat()
            return json.dumps(object)

        return self.renderer.capsules(channel=channel,
                                      capsules=capsules,
                                      expired_capsules=expired_capsules,
                                      capsules_all=capsules_all,
                                      default_from=default_from.replace(microsecond=0).isoformat(),
                                      default_to=default_to.replace(microsecond=0).isoformat(), vertical=vertical,
                                      get_data_edit_object=get_data_edit_object)
