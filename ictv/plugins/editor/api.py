import re
import json
from datetime import datetime
from json import JSONDecodeError

import flask
from flask.wrappers import Response
from sqlobject import SQLObjectNotFound, SQLObjectIntegrityError
from sqlobject.dberrors import DuplicateEntryError

from ictv.models.channel import PluginChannel
from ictv.pages.utils import ICTVPage
from ictv.plugins.editor.editor import EditorCapsule, EditorSlide

from ictv.renderer.renderer import Templates
import ictv.flask.response as resp

class EditorAPIPage(ICTVPage):
    def authenticate(self):
        """ Authenticates the request according to the API key and returns the channel. """
        if len(flask.g.homepath) > 0:  # We are in a sub-app
            channelid = re.findall(r'\d+', flask.g.homepath)[0]
        else:  # We are in the core app
            channelid = re.findall(r'\d+', flask.g.path)[0]
        try:
            channel = PluginChannel.get(channelid)
        except SQLObjectNotFound:
            resp.notfound()

        try:
            if not channel.get_config_param('enable_rest_api'):
                resp.forbidden()
            if not (channel.get_config_param('api_key') or '').strip():
                resp.forbidden()
            if (channel.get_config_param('api_key') or '').strip() != flask.request.environ.get('HTTP_X_ICTV_EDITOR_API_KEY', '').strip():
                resp.forbidden()
        except KeyError:
            resp.forbidden()

        return channel

    def get(self, *args, **kwargs):
        kwargs['channel'] = self.authenticate()
        response = flask.Response(json.dumps(self.GET_AUTH(*args, **kwargs)))
        response.headers['Content-Type'] = 'application/json'
        return response

    def post(self, *args, **kwargs):
        kwargs['channel'] = self.authenticate()
        return self.POST_AUTH(*args, **kwargs)

    def put(self, *args, **kwargs):
        kwargs['channel'] = self.authenticate()
        return self.PUT_AUTH(*args, **kwargs)

    def patch(self, *args, **kwargs):
        kwargs['channel'] = self.authenticate()
        return self.PATCH_AUTH(*args, **kwargs)

    def delete(self, *args, **kwargs):
        kwargs['channel'] = self.authenticate()
        return self.DELETE_AUTH(*args, **kwargs)

    def GET_AUTH(self, *args, **kwargs):
        resp.nomethod()

    def POST_AUTH(self, *args, **kwargs):
        resp.nomethod()

    def PUT_AUTH(self, *args, **kwargs):
        resp.nomethod()

    def PATCH_AUTH(self, *args, **kwargs):
        resp.nomethod()

    def DELETE_AUTH(self, *args, **kwargs):
        resp.nomethod()


class APITemplates(EditorAPIPage):
    def GET_AUTH(self, channel):
        return {k: Templates[k] for k in Templates}


class APIIndex(EditorAPIPage):
    def GET_AUTH(self, channel):
        return [c.to_json_api() for c in EditorCapsule.selectBy(channel=channel)]

    def POST_AUTH(self, channel):
        try:
            post_data = flask.request.get_json(force=True)
        except JSONDecodeError:
            resp.badrequest()

        if {'name', 'theme', 'validity'} != set(post_data.keys()):
            resp.badrequest()

        if 'name' in post_data and len(post_data['name']) < 3:
            resp.badrequest()

        validity_from, validity_to = post_data['validity']
        if not (type(validity_from) == type(validity_to) == int) or validity_to < validity_from:
            resp.badrequest()
        try:
            validity_from, validity_to = datetime.fromtimestamp(validity_from), datetime.fromtimestamp(validity_to)
        except (TypeError, ValueError):
            resp.badrequest()

        try:
            c = EditorCapsule(name=post_data['name'], theme=post_data['theme'], validity_from=validity_from, validity_to=validity_to, channel=channel, c_order=EditorCapsule.selectBy(channel=channel).count())
        except DuplicateEntryError:
            resp.badrequest()
        EditorCapsule.rectify_c_order(channel.id)
        response = resp.created()
        response.headers['Location'] = '/channels/{}/api/capsules/{}'.format(channel.id, c.id)
        return response


class APICapsules(EditorAPIPage):
    def GET_AUTH(self, capsule_id, channel):
        try:
            return EditorCapsule.selectBy(id=int(capsule_id), channel=channel).getOne().to_json_api()
        except SQLObjectNotFound:
            resp.notfound()

    def PATCH_AUTH(self, capsule_id, channel):
        try:
            post_data = flask.request.get_json(force=True)
        except JSONDecodeError:
            resp.badrequest()

        try:
            c = EditorCapsule.selectBy(id=int(capsule_id), channel=channel).getOne()
        except SQLObjectNotFound:
            resp.notfound()

        if 'name' in post_data and len(post_data['name']) < 3:
            resp.badrequest()

        if 'validity' in post_data:
            validity_from, validity_to = post_data['validity']
            if not (type(validity_from) == type(validity_to) == int) or validity_to < validity_from:
                resp.badrequest()
            try:
                validity_from, validity_to = datetime.fromtimestamp(validity_from), datetime.fromtimestamp(validity_to)
            except (TypeError, ValueError):
                resp.badrequest()
            post_data['validity_from'] = validity_from
            post_data['validity_to'] = validity_to
            del post_data['validity']

        update_dict = {k: v for k, v in filter(lambda x: x[0] in ['name', 'theme', 'validity_from', 'validity_to'], post_data.items())}
        try:
            c.set(**update_dict)
        except DuplicateEntryError:
            resp.badrequest()

        resp.nocontent()

    def DELETE_AUTH(self, capsule_id, channel):
        try:
            c = EditorCapsule.selectBy(id=int(capsule_id), channel=channel).getOne()
            c.destroySelf()
        except SQLObjectNotFound:
            resp.notfound()
        resp.nocontent()


class APIIndexSlides(EditorAPIPage):
    def POST_AUTH(self, capsule_id, channel):
        try:
            post_data = flask.request.get_json(force=True)
        except JSONDecodeError:
            resp.badrequest()

        try:
            c = EditorCapsule.selectBy(id=int(capsule_id), channel=channel).getOne()
        except SQLObjectNotFound:
            resp.notfound()

        if {'duration', 'template', 'content'} != set(post_data.keys()):
            resp.badrequest()
        try:
            s = EditorSlide(s_order=c.slides.count(), capsule=c, **post_data)
        except SQLObjectIntegrityError:
            resp.badrequest()

        EditorSlide.rectify_s_order(c.id)
        response = resp.created()
        response.header['Location'] = '/channels/{}/api/capsules/{}/slides/{}'.format(channel.id, capsule_id, s.id)
        return response


class APISlides(EditorAPIPage):
    def GET_AUTH(self, capsule_id, slide_id, channel):
        try:
            EditorCapsule.selectBy(id=int(capsule_id), channel=channel).getOne()
            return EditorSlide.selectBy(id=int(slide_id), capsule=int(capsule_id)).getOne().to_json_api()
        except SQLObjectNotFound:
            resp.notfound()

    def PATCH_AUTH(self, capsule_id, slide_id, channel):
        try:
            post_data = flask.request.get_json(force=True)
        except JSONDecodeError:
            resp.badrequest()

        try:
            c = EditorCapsule.selectBy(id=int(capsule_id), channel=channel).getOne()
            s = EditorSlide.selectBy(id=int(slide_id), capsule=c).getOne()
        except SQLObjectNotFound:
            resp.notfound()

        update_dict = {k: v for k, v in filter(lambda x: x[0] in ['duration', 'template', 'content'], post_data.items())}
        s.set(**update_dict)

        resp.nocontent()

    def DELETE_AUTH(self, capsule_id, slide_id, channel):
        try:
            c = EditorCapsule.selectBy(id=int(capsule_id), channel=channel).getOne()
            EditorSlide.selectBy(id=int(slide_id), capsule=c).getOne().destroySelf()
        except SQLObjectNotFound:
            resp.notfound()

        resp.nocontent()
