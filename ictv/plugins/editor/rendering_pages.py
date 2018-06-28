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

from datetime import datetime

from ictv.plugin_manager.plugin_manager import PluginManager
from ictv.plugin_manager.plugin_utils import ChannelGate
from ictv.plugins.editor.app import EditorPage
from ictv.plugins.editor.editor import EditorCapsule


class RenderExpired(EditorPage):
    @ChannelGate.contributor
    def GET(self, channel):
        capsules = EditorCapsule.selectBy(channel=channel).filter(
            EditorCapsule.q.validity_to <= datetime.now()).orderBy('c_order')
        list_to_render = []
        for c in capsules:
            list_to_render.append(c.to_plugin_capsule())
        PluginManager.dereference_assets(list_to_render)
        return self.ictv_renderer.preview_capsules(list_to_render)


class RenderCurrentAndFuture(EditorPage):
    @ChannelGate.contributor
    def GET(self, channel):
        capsules = EditorCapsule.selectBy(channel=channel).filter(
            EditorCapsule.q.validity_to > datetime.now()).orderBy('c_order')
        list_to_render = []
        for c in capsules:
            list_to_render.append(c.to_plugin_capsule())
        PluginManager.dereference_assets(list_to_render)
        return self.ictv_renderer.preview_capsules(list_to_render)
