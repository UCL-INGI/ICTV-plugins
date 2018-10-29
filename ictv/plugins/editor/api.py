import re
import json
from datetime import datetime
from json import JSONDecodeError

import web
from sqlobject import SQLObjectNotFound, SQLObjectIntegrityError
from sqlobject.dberrors import DuplicateEntryError

from ictv.models.channel import PluginChannel
from ictv.pages.utils import ICTVPage
from ictv.plugins.editor.editor import EditorCapsule, EditorSlide

from ictv.renderer.renderer import Templates

class EditorAPIPage(ICTVPage):
    def authenticate(self):
        """ Authenticates the request according to the API key and returns the channel. """
        if len(web.ctx.homepath) > 0:  # We are in a sub-app
            channelid = re.findall(r'\d+', web.ctx.homepath)[0]
        else:  # We are in the core app
            channelid = re.findall(r'\d+', web.ctx.path)[0]
        try:
            channel = PluginChannel.get(channelid)
        except SQLObjectNotFound:
            raise web.notfound()

        try:
            if not channel.get_config_param('enable_rest_api'):
                raise web.forbidden()
            if not (channel.get_config_param('api_key') or '').strip():
                raise web.forbidden()
            if (channel.get_config_param('api_key') or '').strip() != web.ctx.env.get('HTTP_X_ICTV_EDITOR_API_KEY', '').strip():
                raise web.forbidden()
        except KeyError:
            raise web.forbidden()

        return channel

    def GET(self, *args, **kwargs):
        kwargs['channel'] = self.authenticate()
        web.header('Content-Type', 'application/json')
        return json.dumps(self.GET_AUTH(*args, **kwargs))

    def POST(self, *args, **kwargs):
        kwargs['channel'] = self.authenticate()
        return self.POST_AUTH(*args, **kwargs)

    def PUT(self, *args, **kwargs):
        kwargs['channel'] = self.authenticate()
        return self.PUT_AUTH(*args, **kwargs)

    def PATCH(self, *args, **kwargs):
        kwargs['channel'] = self.authenticate()
        return self.PATCH_AUTH(*args, **kwargs)

    def DELETE(self, *args, **kwargs):
        kwargs['channel'] = self.authenticate()
        return self.DELETE_AUTH(*args, **kwargs)

    def GET_AUTH(self, *args, **kwargs):
        raise web.nomethod()

    def POST_AUTH(self, *args, **kwargs):
        raise web.nomethod()

    def PUT_AUTH(self, *args, **kwargs):
        raise web.nomethod()

    def PATCH_AUTH(self, *args, **kwargs):
        raise web.nomethod()

    def DELETE_AUTH(self, *args, **kwargs):
        raise web.nomethod()


class APITemplates(EditorAPIPage):
    def GET_AUTH(self, channel):
        return {k: Templates[k] for k in Templates}


class APIIndex(EditorAPIPage):
    def GET_AUTH(self, channel):
        return [c.to_json_api() for c in EditorCapsule.selectBy(channel=channel)]

    def POST_AUTH(self, channel):
        try:
            post_data = json.loads(web.data().decode())
        except JSONDecodeError:
            raise web.badrequest()

        if {'name', 'theme', 'validity'} != set(post_data.keys()):
            raise web.badrequest()

        if 'name' in post_data and len(post_data['name']) < 3:
            raise web.badrequest()

        validity_from, validity_to = post_data['validity']
        if not (type(validity_from) == type(validity_to) == int) or validity_to < validity_from:
            raise web.badrequest()
        try:
            validity_from, validity_to = datetime.fromtimestamp(validity_from), datetime.fromtimestamp(validity_to)
        except (TypeError, ValueError):
            raise web.badrequest()

        try:
            c = EditorCapsule(name=post_data['name'], theme=post_data['theme'], validity_from=validity_from, validity_to=validity_to, channel=channel, c_order=EditorCapsule.selectBy(channel=channel).count())
        except DuplicateEntryError:
            raise web.badrequest()
        EditorCapsule.rectify_c_order(channel.id)
        web.header('Location', '/channels/{}/api/capsules/{}'.format(channel.id, c.id))
        raise web.created()


class APICapsules(EditorAPIPage):
    def GET_AUTH(self, capsule_id, channel):
        try:
            return EditorCapsule.selectBy(id=int(capsule_id), channel=channel).getOne().to_json_api()
        except SQLObjectNotFound:
            raise web.notfound()

    def PATCH_AUTH(self, capsule_id, channel):
        try:
            post_data = json.loads(web.data().decode())
        except JSONDecodeError:
            raise web.badrequest()

        try:
            c = EditorCapsule.selectBy(id=int(capsule_id), channel=channel).getOne()
        except SQLObjectNotFound:
            raise web.notfound()

        if 'name' in post_data and len(post_data['name']) < 3:
            raise web.badrequest()

        if 'validity' in post_data:
            validity_from, validity_to = post_data['validity']
            if not (type(validity_from) == type(validity_to) == int) or validity_to < validity_from:
                raise web.badrequest()
            try:
                validity_from, validity_to = datetime.fromtimestamp(validity_from), datetime.fromtimestamp(validity_to)
            except (TypeError, ValueError):
                raise web.badrequest()
            post_data['validity_from'] = validity_from
            post_data['validity_to'] = validity_to
            del post_data['validity']

        update_dict = {k: v for k, v in filter(lambda x: x[0] in ['name', 'theme', 'validity_from', 'validity_to'], post_data.items())}
        try:
            c.set(**update_dict)
        except DuplicateEntryError:
            raise web.badrequest()

        raise web.nocontent()

    def DELETE_AUTH(self, capsule_id, channel):
        try:
            c = EditorCapsule.selectBy(id=int(capsule_id), channel=channel).getOne()
            c.destroySelf()
        except SQLObjectNotFound:
            raise web.notfound()
        raise web.nocontent()


class APIIndexSlides(EditorAPIPage):
    def POST_AUTH(self, capsule_id, channel):
        try:
            post_data = json.loads(web.data().decode())
        except JSONDecodeError:
            raise web.badrequest()

        try:
            c = EditorCapsule.selectBy(id=int(capsule_id), channel=channel).getOne()
        except SQLObjectNotFound:
            raise web.notfound()

        if {'duration', 'template', 'content'} != set(post_data.keys()):
            raise web.badrequest()
        try:
            s = EditorSlide(s_order=c.slides.count(), capsule=c, **post_data)
        except SQLObjectIntegrityError:
            raise web.badrequest()

        EditorSlide.rectify_s_order(c.id)
        web.header('Location', '/channels/{}/api/capsules/{}/slides/{}'.format(channel.id, capsule_id, s.id))
        raise web.created()


class APISlides(EditorAPIPage):
    def GET_AUTH(self, capsule_id, slide_id, channel):
        try:
            EditorCapsule.selectBy(id=int(capsule_id), channel=channel).getOne()
            return EditorSlide.selectBy(id=int(slide_id), capsule=int(capsule_id)).getOne().to_json_api()
        except SQLObjectNotFound:
            raise web.notfound()

    def PATCH_AUTH(self, capsule_id, slide_id, channel):
        try:
            post_data = json.loads(web.data().decode())
        except JSONDecodeError:
            raise web.badrequest()

        try:
            c = EditorCapsule.selectBy(id=int(capsule_id), channel=channel).getOne()
            s = EditorSlide.selectBy(id=int(slide_id), capsule=c).getOne()
        except SQLObjectNotFound:
            raise web.notfound()

        update_dict = {k: v for k, v in filter(lambda x: x[0] in ['duration', 'template', 'content'], post_data.items())}
        s.set(**update_dict)

        raise web.nocontent()

    def DELETE_AUTH(self, capsule_id, slide_id, channel):
        try:
            c = EditorCapsule.selectBy(id=int(capsule_id), channel=channel).getOne()
            EditorSlide.selectBy(id=int(slide_id), capsule=c).getOne().destroySelf()
        except SQLObjectNotFound:
            raise web.notfound()

        raise web.nocontent()
