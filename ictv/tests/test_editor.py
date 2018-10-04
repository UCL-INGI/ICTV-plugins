import json
from datetime import datetime, timedelta

from ictv.models.channel import PluginChannel
from ictv.models.plugin import Plugin
from ictv.plugins.editor.editor import EditorCapsule, EditorSlide
from ictv.tests import ICTVTestCase


class EditorAPITest(ICTVTestCase):
    def _pre_app_start(self):
        self.channel = PluginChannel(plugin=Plugin.selectBy(name='editor').getOne(), name='Editor API', subscription_right='public')
        self.channel2 = PluginChannel(plugin=Plugin.selectBy(name='editor').getOne(), name='Editor API 2', subscription_right='public', plugin_config={'enable_rest_api': True, 'api_key': 'aaaaaaaa'})

    def setUp(self):
        super(EditorAPITest, self).setUp(middleware=lambda: self._pre_app_start())
        self.set_patch()

    def set_patch(self):
        testApp = self.testApp

        def patch(url, params=b'', headers=None, extra_environ=None,
                 status=None, upload_files=None, expect_errors=False):
            """
            Do a PATCH request.  Very like the ``.get()`` method.
            ``params`` are put in the body of the request.

            ``upload_files`` is for file uploads.  It should be a list of
            ``[(fieldname, filename, file_content)]``.  You can also use
            just ``[(fieldname, filename)]`` and the file content will be
            read from disk.

            Returns a `response object
            <class-paste.fixture.TestResponse.html>`_
            """
            return testApp._gen_request('PATCH', url, params=params, headers=headers,
                                     extra_environ=extra_environ,status=status,
                                     upload_files=upload_files,
                                     expect_errors=expect_errors)
        testApp.patch = patch


class AuthTest(EditorAPITest):
    def runTest(self):
        """ Tests the authentication. """
        self.testApp.get('/channels/{}/api/capsules'.format(self.channel.id), status=403)
        self.channel.plugin_config['enable_rest_api'] = True
        self.testApp.get('/channels/{}/api/capsules'.format(self.channel.id), status=403)
        self.channel.plugin_config['api_key'] = 'aaaaaaaa'
        self.testApp.get('/channels/{}/api/capsules'.format(self.channel.id), status=403)
        r = self.testApp.get('/channels/{}/api/capsules'.format(self.channel.id), status=200, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        assert r.body.decode() == '[]'
        self.testApp.get('/channels/{}/api/capsules'.format(self.channel.id), status=403, headers={'X-ICTV-editor-API-Key': 'aaaaaaab'})
        self.testApp.get('/channels/{}/api/capsules'.format(self.channel.id), status=403, headers={'X-ICTV-editor-API-Key': ''})


class GETTest(EditorAPITest):
    def runTest(self):
        """ Tests the GET endpoints. """
        self.channel.plugin_config['enable_rest_api'] = True
        self.channel.plugin_config['api_key'] = 'aaaaaaaa'
        validity_from = datetime(2018, 10, 2, 12, 00)
        validity_to = datetime(2018, 10, 2, 14, 00)
        api_capsule = EditorCapsule(name='api_capsule', channel=self.channel, creation_date=datetime.now(), c_order=0, validity_from=validity_from, validity_to=validity_to, theme='ictv')
        r = self.testApp.get('/channels/{}/api/capsules'.format(self.channel.id), status=200, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        assert r.body.decode() == '[{"id": 1, "name": "api_capsule", "slides": [], "validity": [1538474400, 1538481600], "theme": "ictv"}]'
        EditorCapsule(name='api_capsule2', channel=self.channel, creation_date=datetime.now(), c_order=1, validity_from=validity_from + timedelta(minutes=1), validity_to=validity_to, theme='ictv')
        r = self.testApp.get('/channels/{}/api/capsules'.format(self.channel.id), status=200, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        assert r.body.decode() == '[{"id": 1, "name": "api_capsule", "slides": [], "validity": [1538474400, 1538481600], "theme": "ictv"}, {"id": 2, "name": "api_capsule2", "slides": [], "validity": [1538474460, 1538481600], "theme": "ictv"}]'
        EditorSlide(duration=42, s_order=0, template='api-template', capsule=api_capsule)
        r = self.testApp.get('/channels/{}/api/capsules'.format(self.channel.id), status=200, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        assert r.body.decode() == '[{"id": 1, "name": "api_capsule", "slides": [{"id": 1, "duration": 42, "content": {}, "template": "api-template"}], "validity": [1538474400, 1538481600], "theme": "ictv"}, {"id": 2, "name": "api_capsule2", "slides": [], "validity": [1538474460, 1538481600], "theme": "ictv"}]'
        r = self.testApp.get('/channels/{}/api/capsules/1'.format(self.channel.id), status=200, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        assert r.body.decode() == '{"id": 1, "name": "api_capsule", "slides": [{"id": 1, "duration": 42, "content": {}, "template": "api-template"}], "validity": [1538474400, 1538481600], "theme": "ictv"}'
        r = self.testApp.get('/channels/{}/api/capsules/1/slides/1'.format(self.channel.id), status=200, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        assert r.body.decode() == '{"id": 1, "duration": 42, "content": {}, "template": "api-template"}'


class CapsuleTest(EditorAPITest):
    def runTest(self):
        """ Tests the capsules endpoint. """
        self.channel.plugin_config['enable_rest_api'] = True
        self.channel.plugin_config['api_key'] = 'aaaaaaaa'

        r = self.testApp.get('/channels/{}/api/capsules'.format(self.channel.id), status=200, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        assert r.body.decode() == '[]'

        capsule_json = {"name": "A fine capsule", "theme": "ictv", "validity": [1538474400, 1539079200]}

        r = self.testApp.post('/channels/{}/api/capsules'.format(self.channel.id), status=201, params=json.dumps(capsule_json).encode(), headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        r = self.testApp.get(r.header('Location'), status=200, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        assert r.body.decode() == '{"id": 1, "name": "A fine capsule", "slides": [], "validity": [1538474400, 1539079200], "theme": "ictv"}'
        r = self.testApp.get('/channels/{}/api/capsules'.format(self.channel.id), status=200, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        assert r.body.decode() == '[{"id": 1, "name": "A fine capsule", "slides": [], "validity": [1538474400, 1539079200], "theme": "ictv"}]'

        capsule_json["name"] = "Another capsule name"
        self.testApp.post('/channels/{}/api/capsules'.format(self.channel.id), status=201, params=json.dumps(capsule_json).encode(), headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        r = self.testApp.get('/channels/{}/api/capsules'.format(self.channel.id), status=200, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        assert r.body.decode() == '[{"id": 1, "name": "A fine capsule", "slides": [], "validity": [1538474400, 1539079200], "theme": "ictv"}, {"id": 2, "name": "Another capsule name", "slides": [], "validity": [1538474400, 1539079200], "theme": "ictv"}]'

        self.testApp.patch('/channels/{}/api/capsules/1'.format(self.channel.id), status=400, params=json.dumps({"name": "A new name", "slides": ["A"], "validity": [1539079200, 1538474400]}), headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        self.testApp.patch('/channels/{}/api/capsules/1'.format(self.channel.id), status=400, params=json.dumps({"name": "A new name", "slides": ["A"], "validity": [1539079200, ""]}), headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        self.testApp.patch('/channels/{}/api/capsules/1'.format(self.channel.id), status=204, params=json.dumps({"name": "A new name", "slides": ["A"], "validity": [0, 1539079200]}), headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        r = self.testApp.get('/channels/{}/api/capsules/1'.format(self.channel.id), status=200, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        assert r.body.decode() == '{"id": 1, "name": "A new name", "slides": [], "validity": [0, 1539079200], "theme": "ictv"}'

        self.testApp.patch('/channels/{}/api/capsules/2'.format(self.channel.id), status=400, params=json.dumps({"name": "A new name"}), headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})

        self.testApp.delete('/channels/{}/api/capsules/3'.format(self.channel.id), status=404, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        self.testApp.delete('/channels/{}/api/capsules/1'.format(self.channel.id), status=204, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})

        self.testApp.post('/channels/{}/api/capsules'.format(self.channel2.id), status=201, params=json.dumps(capsule_json).encode(), headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        self.testApp.delete('/channels/{}/api/capsules/3'.format(self.channel.id), status=404, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})

        r = self.testApp.get('/channels/{}/api/capsules'.format(self.channel.id), status=200,
                             headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        assert r.body.decode() == '[{"id": 2, "name": "Another capsule name", "slides": [], "validity": [1538474400, 1539079200], "theme": "ictv"}]'


class SlideTest(EditorAPITest):
    def runTest(self):
        """ Tests the slides endpoints. """
        self.channel.plugin_config['enable_rest_api'] = True
        self.channel.plugin_config['api_key'] = 'aaaaaaaa'
        capsule_json = {"name": "A fine capsule", "theme": "ictv", "validity": [1538474400, 1539079200]}

        slide_json = {"duration": 5000, "template": "template-text-center", "content": {"title-1": {"text": "Awesome title!"}, "subtitle-1": {"text": "Subtile subtitle"}, "text-1": {"text": "Very long textual text here"}, "image-1": {"src": "http://thecatapi.com/api/images/get"}, "logo-1": {"src": "michelfra.svg"}}}

        self.testApp.get('/channels/{}/api/capsules/1/slides/1'.format(self.channel.id), status=404, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        r = self.testApp.post('/channels/{}/api/capsules'.format(self.channel.id), status=201, params=json.dumps(capsule_json).encode(), headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        r = self.testApp.post(r.header('Location') + '/slides', status=201, params=json.dumps(slide_json).encode(), headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        r = self.testApp.get(r.header('Location'), status=200, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        assert r.body.decode() == '{"id": 1, "duration": 5000, "content": {"title-1": {"text": "Awesome title!"}, "subtitle-1": {"text": "Subtile subtitle"}, "text-1": {"text": "Very long textual text here"}, "image-1": {"src": "http://thecatapi.com/api/images/get"}, "logo-1": {"src": "michelfra.svg"}}, "template": "template-text-center"}'

        capsule_json['name'] = 'Capsule 2'
        r = self.testApp.post('/channels/{}/api/capsules'.format(self.channel.id), status=201, params=json.dumps(capsule_json).encode(), headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        self.testApp.get(r.header('Location') + '/slides/1', status=404, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})

        slide_json['content']['title-1']['text'] = 'A second awesome slide'
        self.testApp.post('/channels/{}/api/capsules/1/slides'.format(self.channel.id), status=201, params=json.dumps(slide_json).encode(), headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})

        self.testApp.patch('/channels/{}/api/capsules/1/slides/1'.format(self.channel.id), status=204, params=json.dumps({'duration': 4000}).encode(), headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})

        r = self.testApp.get('/channels/{}/api/capsules/1/slides/1'.format(self.channel.id), status=200, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        assert r.body.decode() == '{"id": 1, "duration": 4000, "content": {"title-1": {"text": "Awesome title!"}, "subtitle-1": {"text": "Subtile subtitle"}, "text-1": {"text": "Very long textual text here"}, "image-1": {"src": "http://thecatapi.com/api/images/get"}, "logo-1": {"src": "michelfra.svg"}}, "template": "template-text-center"}'

        self.testApp.delete('/channels/{}/api/capsules/2/slides/1'.format(self.channel.id), status=404, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        self.testApp.get('/channels/{}/api/capsules/1/slides/1'.format(self.channel.id), status=200, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        self.testApp.delete('/channels/{}/api/capsules/1/slides/1'.format(self.channel.id), status=204, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
        self.testApp.get('/channels/{}/api/capsules/1/slides/1'.format(self.channel.id), status=404, headers={'X-ICTV-editor-API-Key': 'aaaaaaaa'})
