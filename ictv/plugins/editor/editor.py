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

import ipaddress
import os
import socket
from base64 import b64encode
from datetime import datetime
from urllib.parse import urlparse

import magic
import web
from sqlobject import AND, JSONCol, sqlhub
from sqlobject import IntCol, StringCol, ForeignKey, DateTimeCol, SQLMultipleJoin, DatabaseIndex, \
    SQLObject
from sqlobject.dberrors import DuplicateEntryError
from sqlobject.events import listen, RowDestroyedSignal
from typing import Iterable

from ictv.models.asset import Asset
from ictv.models.channel import PluginChannel
from ictv.models.plugin import Plugin
from ictv.models.user import User
from ictv.plugin_manager.plugin_capsule import PluginCapsule
from ictv.plugin_manager.plugin_slide import PluginSlide
from ictv.plugin_manager.plugin_utils import SQLObjectAndABCMeta, VideoSlide, MisconfiguredParameters
from ictv.storage.cache_manager import CacheManager


def get_content(channelid, capsuleid=None) -> Iterable[PluginCapsule]:
    content = []
    channel = PluginChannel.get(channelid)
    if 0 < len(channel.get_config_param('api_key')) < 8:
        raise MisconfiguredParameters('api_key', channel.get_config_param('api_key'), "The key must be at least 8-character long")
    if capsuleid is None:
        now = datetime.now()
        capsules = EditorCapsule.selectBy(channel=channelid).filter(
            AND(EditorCapsule.q.validity_to > now, EditorCapsule.q.validity_from < now)).orderBy("c_order")
        for c in capsules:
            content.append(c.to_plugin_capsule())
    else:
        content = [EditorCapsule.get(capsuleid).to_plugin_capsule()]
    for capsule in content:
        for slide in capsule.get_slides():
            if channel.get_config_param('force_duration') or slide.duration == -1:
                slide.duration = int(channel.get_config_param('duration') * 1000)
    return content


class EditorPluginCapsule(PluginCapsule):
    def __init__(self, theme=None):
        self.theme = theme
        self.slides = []

    def get_slides(self) -> Iterable[PluginSlide]:
        return self.slides

    def add_slide(self, slide):
        self.slides.append(slide)

    def get_theme(self) -> str:
        return self.theme


class EditorPluginSlide(PluginSlide):
    def __init__(self, content, template, duration=5000):
        self.content = content
        self.template = template
        self.duration = duration

    def get_duration(self) -> int:
        return self.duration

    def get_content(self):
        return self.content

    def get_template(self) -> str:
        return self.template


class AssetSlideMapping(SQLObject):
    asset = ForeignKey('Asset', cascade=True)
    slide = ForeignKey('EditorSlide', cascade=True)


def on_mapping_deleted(instance, kwargs):
    """ Deletes the file associated with this asset when this asset is deleted. """
    if AssetSlideMapping.selectBy(assetID=instance.asset.id).count() == 0:
        instance.asset.destroySelf()


listen(on_mapping_deleted, AssetSlideMapping, RowDestroyedSignal)


class EditorSlide(SQLObject, PluginSlide, metaclass=SQLObjectAndABCMeta):
    duration = IntCol(notNone=True)
    content = JSONCol(notNone=True, default={})
    s_order = IntCol(notNone=True)
    template = StringCol(notNone=True)
    capsule = ForeignKey('EditorCapsule', cascade=True)
    asset_mappings = SQLMultipleJoin('AssetSlideMapping')

    @classmethod
    def from_slide(cls, slide: PluginSlide, capsule, slide_order=0):
        def create_asset_mappings(slide):
            for field, inputs in slide.get_content().items():
                if 'file' in inputs:
                    AssetSlideMapping(slide=slide, asset=inputs['file'])
        s = EditorSlide(content=slide.get_content(), duration=slide.get_duration(), template=slide.get_template(),
                        capsule=capsule, s_order=slide_order)
        create_asset_mappings(s)
        return s

    @classmethod
    def from_video(cls, video, storage_manager, transcoding_manager, capsule, user, background_color):
        def create_slide(asset_id, capsule_id):
            video_slide = cls.from_slide(VideoSlide({'file': asset_id}, template='template-image-bg'),
                                         capsule=capsule_id)
            video_slide.content['background-1'].update({'size': 'contain', 'color': background_color})
            video_slide.content = video_slide.content  # Force SQLObject update
            capsule = EditorCapsule.get(capsule_id)
            capsule.insert_slide_at(video_slide, capsule.slides.count())
            return video_slide

        # TODO: Stream asset to disk instead of loading it into memory
        video_blob = video.file.read()
        if magic.from_buffer(video_blob, mime=True) != 'video/webm':
            def transcode_callback(success_status):
                if success_status:
                    create_slide(video_asset_id, capsule_id)
                    video_asset.file_size = os.path.getsize(video_asset.path)
                else:
                    video_asset.destroySelf()
                original_video_asset.destroySelf()

            original_video_asset = storage_manager.store_file(video_blob, filename=video.filename, user=user)
            video_asset = storage_manager.create_asset(filename=video.filename + os.extsep + '.webm', user=user, mime_type='video/webm')
            video_asset_id, capsule_id = video_asset.id, capsule.id
            transcoding_manager.enqueue_task(original_video_asset.path, video_asset.path, transcode_callback)
            return video_asset.path
        else:
            video_asset = storage_manager.store_file(video_blob, filename=video.filename, user=user)
            return create_slide(video_asset.id, capsule.id)

    def _init(self, id, connection=None, selectResults=None):
        return super()._init(id, connection, selectResults)

    @classmethod
    def rectify_s_order(cls, capsule_id):
        slide_list = list(EditorSlide.select(EditorSlide.q.capsule == capsule_id, orderBy=EditorSlide.q.s_order))
        if len(slide_list) > 0 and slide_list[0].s_order == 0 and slide_list[-1].s_order == len(slide_list) - 1:
            return slide_list
        i = 0
        for s in slide_list:
            s.s_order = i
            i += 1
        return slide_list

    def to_plugin_slide(self) -> EditorPluginSlide:
        return EditorPluginSlide(content=self.content, template=self.template, duration=int(self.duration))

    def get_duration(self) -> int:
        return self.duration

    def get_duration_or_default(self):
        int(self.capsule.channel.plugin_config['duration']) * 1000 if 'duration' in self.capsule.channel.plugin_config \
            else int(self.capsule.channel.plugin.channels_params['duration']['default']) * 1000

    def get_content(self):
        return self.content

    def get_template(self) -> str:
        return self.template

    def duplicate(self, capsule=None, s_order=None):
        """
        :return: a slide identical to this slide. If the capsule and arguments are not specified, they are the same
        as this slide. It also duplicates the AssetSlideMappings of this slide
        """
        capsule = capsule if capsule is not None else self.capsule
        s_order = s_order if s_order is not None else self.s_order
        duplicate = EditorSlide(duration=self.duration, content=self.get_content(),
                                s_order=s_order, template=self.get_template(), capsule=capsule)
        for mapping in AssetSlideMapping.selectBy(slide=self.id):
            AssetSlideMapping(assetID=mapping.asset.id, slideID=duplicate.id)
        return duplicate

    def get_render_path(self, ictv_home=None):
        if ictv_home is None:
            ictv_home = web.ctx.home
        return '%s%s/%d/%d' % (ictv_home, 'render', self.capsule.id, self.id)

    @property
    def contains_video(self):
        for field, inputs in self.content.items():
            if 'file' in inputs:
                if Asset.get(inputs['file']).mime_type.startswith('video'):
                    return True
            elif 'video' in inputs:
                return True
        return False

    def to_json_api(self):
        return {
            'id': self.id,
            'duration': self.duration,
            'content': self.content,
            'template': self.template,
        }


class EditorCapsule(SQLObject, PluginCapsule, metaclass=SQLObjectAndABCMeta):
    name = StringCol()
    owner = ForeignKey('User', cascade='null', default=None)
    channel = ForeignKey('PluginChannel', cascade=True)
    capsule_id = DatabaseIndex('name', 'channel', unique=True)
    creation_date = DateTimeCol(notNone=True, default=lambda: datetime.now())
    slides = SQLMultipleJoin('EditorSlide', joinColumn='capsule_id')
    theme = StringCol(default=lambda: web.ctx.app_stack[0].config['default_theme'])
    c_order = IntCol(notNone=True)
    validity_from = DateTimeCol(notNone=True)
    validity_to = DateTimeCol(notNone=True)

    @classmethod
    def rectify_c_order(cls, channel_id):
        capsules_list = list(
            EditorCapsule.select(EditorCapsule.q.channel == channel_id, orderBy=EditorCapsule.q.c_order))
        if len(capsules_list) > 0 and capsules_list[0].c_order == 0 and capsules_list[-1].c_order == len(
                capsules_list) - 1:
            return EditorCapsule.select(EditorCapsule.q.channel == channel_id, orderBy=EditorCapsule.q.c_order)
        i = 0
        for c in capsules_list:
            c.c_order = i
            i += 1
        return EditorCapsule.select(EditorCapsule.q.channel == channel_id, orderBy=EditorCapsule.q.c_order)

    def insert_slide_at(self, slide, index):
        """
        inserts the slide at the correct position of the slides list of the capsule, updating the s_order of the
        slides located after the index position in the list.
        """
        # get the slides of the capsule, ordered by their s_order
        slides = list(EditorSlide.select(EditorSlide.q.capsule == self.id, orderBy=EditorSlide.q.s_order))
        # set the s_order of the new slide
        slide.s_order = index
        slide.capsule = self.id
        # update the s_order of all the slides with a s_order >= the s_order of this slide
        for i in range(index, len(slides)):
            slides[i].s_order += 1
        EditorSlide.rectify_s_order(self.id)

    def to_plugin_capsule(self) -> EditorPluginCapsule:
        caps = EditorPluginCapsule(theme=self.theme)
        for s in sorted(self.slides, key=lambda slide: slide.s_order):
            caps.add_slide(s.to_plugin_slide())
        return caps

    def get_slides(self) -> Iterable[PluginSlide]:
        return self.slides

    def get_theme(self) -> str:
        return self.theme

    def _get_is_active(self):
        now = datetime.now()
        return self.validity_from <= now < self.validity_to

    def _get_pretty_from(self):
        return str(self.validity_from.replace(microsecond=0).isoformat(' '))

    def duplicate(self, owner_id, c_order=None):
        """
        :return: a duplicate of this capsule belonging to the specified owner_id and containing a duplicate
        of the slides of this capsule.
        If c_order is not specified, the duplicate has the same c_order as this capsule.
        """
        c_order = c_order if c_order is not None else self.c_order

        def create_capsule(name):
            try:
                return EditorCapsule(name=name + '-copy', channel=self.channel, ownerID=owner_id,
                                     creation_date=self.creation_date,
                                     c_order=c_order, validity_from=self.validity_from,
                                     validity_to=self.validity_to)
            except DuplicateEntryError:
                return create_capsule(name + '-copy')

        duplicate = create_capsule(str(self.name))
        for slide in self.slides:
            EditorSlide.from_slide(slide=slide, capsule=duplicate)
        return duplicate

    def to_json_api(self):
        return {
            'id': self.id,
            'name': self.name,
            'slides': [s.to_json_api() for s in self.slides],
            'validity': [int(self.validity_from.timestamp()), int(self.validity_to.timestamp())],
            'theme': self.theme,
        }


def install():
    EditorCapsule.createTable(ifNotExists=True)
    EditorSlide.createTable(ifNotExists=True)
    AssetSlideMapping.createTable(ifNotExists=True)
    Plugin.selectBy(name='editor').getOne().version = 0


def update(plugin):
    if plugin.version < 1:
        # Do the update
        # plugin.version = 1
        pass
