# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import unittest

from zope.interface import implements

import pyramid.testing
import pyramid.request
from pyramid.interfaces import IRequestFactory, IAuthenticationPolicy
from pyramid.authorization import ACLAuthorizationPolicy
from pyramid.security import authenticated_userid
from pyramid.request import Request

import mozsvc.user


class HeaderAuthenticationPolicy(object):
    """Authentication policy taking creds from request headers."""

    implements(IAuthenticationPolicy)

    def authenticated_userid(self, request):
        username = request.environ.get("HTTP_X_USERNAME")
        if not username:
            return None
        password = request.environ.get("HTTP_X_PASSWORD")
        if not password:
            return None
        credentials = {"username": username, "password": password}
        if not mozsvc.user.authenticate(request, credentials, ["mail"]):
            return None
        request.user["x-was-ere"] = True
        return username

    def unauthenticated_userid(self, request):
        raise RuntimeError("tests shouldn't call this")  # pragma: nocover

    def effective_principals(self, request):
        raise RuntimeError("tests shouldn't call this")  # pragma: nocover


class TestCaseHelpers(object):

    DEFAULT_SETTINGS = {
        'cef.vendor': 'mozilla',
        'cef.device_version': '1.3',
        'cef.product': 'weave',
        'cef.use': True,
        'cef.version': 0,
        'cef.file': 'syslog',
    }

    def setUp(self):
        self.config = pyramid.testing.setUp()
        self.config.add_settings(self.DEFAULT_SETTINGS)

    def tearDown(self):
        pyramid.testing.tearDown()

    def _make_request(self, environ=None, factory=None):
        my_environ = {}
        my_environ["wsgi.version"] = "1.0"
        my_environ["REQUEST_METHOD"] = "GET"
        my_environ["SCRIPT_NAME"] = ""
        my_environ["PATH_INFO"] = "/"
        if environ is not None:
            my_environ.update(environ)
        if factory is None:
            factory = self.config.registry.getUtility(IRequestFactory)
        request = factory(my_environ)
        request.registry = self.config.registry
        return request


class UserTestCase(TestCaseHelpers, unittest.TestCase):

    DEFAULT_SETTINGS = TestCaseHelpers.DEFAULT_SETTINGS.copy()
    DEFAULT_SETTINGS.update({
        "auth.backend": "services.user.memory.MemoryUser",
    })

    def setUp(self):
        super(UserTestCase, self).setUp()
        self.config.include("mozsvc.user")
        self.config.set_authorization_policy(ACLAuthorizationPolicy())
        self.config.set_authentication_policy(HeaderAuthenticationPolicy())
        self.auth = self.config.registry["auth"]
        self.auth.create_user("user1", "password1", "test@mozilla.com")

    def test_auth_backend_is_loaded(self):
        self.assertEquals(self.config.registry["auth"].__class__.__name__,
                          "MemoryUser")

    def test_authenticate(self):
        request = self._make_request()
        # We have no IAuthenticationPolicy, so initially req.user is False.
        self.assertFalse(request.user)
        # After authenticating, it will be replaced with the user object.
        credentials = {"username": "user1", "password": "password1"}
        mozsvc.user.authenticate(request, credentials)
        self.assertEquals(request.user["username"], "user1")

    def test_authenticate_with_normal_request_object(self):
        request = self._make_request(factory=Request)
        # Initially it has no user attribute.
        self.assertRaises(AttributeError, getattr, request, "user")
        # After authenticating, it will have the user object.
        credentials = {"username": "user1", "password": "password1"}
        mozsvc.user.authenticate(request, credentials)
        self.assertEquals(request.user["username"], "user1")

    def test_authenticate_with_no_backend(self):
        del self.config.registry["auth"]
        request = self._make_request()
        credentials = {"username": "user1", "password": "password1"}
        self.assertFalse(mozsvc.user.authenticate(request, credentials))
        self.assertEquals(request.user, {})

    def test_authenticate_with_repozewho_style_credentials(self):
        request = self._make_request()
        credentials = {"login": "user1", "password": "password1"}
        mozsvc.user.authenticate(request, credentials)
        self.assertEquals(request.user["username"], "user1")

    def test_authenticate_with_bad_password(self):
        request = self._make_request()
        credentials = {"username": "user1", "password": "BAD BAD BAD"}
        self.assertFalse(mozsvc.user.authenticate(request, credentials))
        self.assertEquals(request.user, {})

    def test_authenticate_with_unicode_password(self):
        credentials = {"username": "user1", "password": "password1"}
        new_password = u"password\N{GREEK SMALL LETTER ALPHA}"
        self.auth.update_password({"username": "user1"}, credentials,
                                  new_password)
        # Auth works with unicode password.
        request = self._make_request()
        credentials = {"username": "user1", "password": new_password}
        self.assertTrue(mozsvc.user.authenticate(request, credentials))
        # Auth works with utf-encoded password.
        request = self._make_request()
        credentials = {"username": "user1",
                       "password": new_password.encode("utf8")}
        self.assertTrue(mozsvc.user.authenticate(request, credentials))
        # Auth fails with badly-encoded password
        request = self._make_request()
        credentials = {"username": "user1",
                       "password": new_password.encode("utf16")}
        self.assertFalse(mozsvc.user.authenticate(request, credentials))

    def test_authenticate_with_unknown_username(self):
        request = self._make_request()
        credentials = {"username": "user2", "password": "password1"}
        self.assertFalse(mozsvc.user.authenticate(request, credentials))
        self.assertEquals(request.user, {})

    def test_authenticate_with_no_username(self):
        request = self._make_request()
        credentials = {"usernme": "user2", "password": "password1"}
        self.assertFalse(mozsvc.user.authenticate(request, credentials))
        self.assertEquals(request.user, {})

    def test_includeme_with_bad_backend(self):
        config = pyramid.testing.setUp()
        self.config.add_settings({
            "auth.backend": "this.does.not.exist",
        })
        config.include("mozsvc.user")
        self.assertEquals(config.registry["auth"], None)
        request = self._make_request()
        self.assertEquals(request.user, {})

    def test_req_user_success(self):
        request = self._make_request({
                    "HTTP_X_USERNAME": "user1",
                    "HTTP_X_PASSWORD": "password1",
                  })
        self.assertEquals(request.user["username"], "user1")
        self.assertEquals(request.user.get("password"), None)
        self.assertEquals(request.user["mail"], "test@mozilla.com")
        self.assertEquals(request.user["x-was-ere"], True)

    def test_req_user_bad_password(self):
        request = self._make_request({
                    "HTTP_X_USERNAME": "user1",
                    "HTTP_X_PASSWORD": "random_guess",
                  })
        self.assertFalse(request.user)

    def test_req_user_no_username(self):
        request = self._make_request({
                    "HTTP_X_PASSWORD": "password1",
                  })
        self.assertFalse(request.user)

    def test_req_user_no_password(self):
        request = self._make_request({
                    "HTTP_X_USERNAME": "user1",
                  })
        self.assertFalse(request.user)

    def test_req_user_exposes_repoze_who_identity(self):
        # An existing r.w.i dict is exposed as req.user.
        request = self._make_request({
                    "repoze.who.identity": {"repoze-was-ere": True},
                  })
        self.assertEquals(request.user["repoze-was-ere"], True)
        # Setting a key in req.user also sets it in r.w.i.
        request.user["testing"] = "testing"
        self.assertEquals(request.environ["repoze.who.identity"]["testing"],
                          "testing")
        # Replacing req.user also replaces r.w.i
        request.user = {"replacement": "text"}
        self.assertEquals(request.environ["repoze.who.identity"].keys(),
                          ["replacement"])

    def test_registry_is_stored_in_environment(self):
        request = self._make_request()
        self.assertEquals(self.config.registry, request.registry)
        self.assertEquals(self.config.registry,
                          request.environ["mozsvc.user.registry"])
        del request.environ["mozsvc.user.registry"]
        self.assertRaises(AttributeError, getattr, request, "registry")


class FakeAuthPlugin(object):
    def authenticate(self, environ, identity):
        raise RuntimeError("should not run")  # pragma: nocover


class FakeIdentifierPlugin(object):
    def identify(self, environ, identity):
        raise RuntimeError("should not run")  # pragma: nocover


class UserWhoAuthTestCase(TestCaseHelpers, unittest.TestCase):

    DEFAULT_SETTINGS = TestCaseHelpers.DEFAULT_SETTINGS.copy()
    DEFAULT_SETTINGS.update({
        "auth.backend": "services.user.memory.MemoryUser",
    })

    def setUp(self):
        super(UserWhoAuthTestCase, self).setUp()
        self.config.include("mozsvc.user.whoauth")
        self.auth = self.config.registry["auth"]
        self.auth.create_user("user1", "password1", "test@mozilla.com")

    def test_that_basic_auth_is_used_by_default(self):
        # With no who-specific settings, we get a backend authenticator
        # and use basic-auth for identification and challenge.
        authz = "Basic " + "user1:password1".encode("base64").strip()
        req = self._make_request({
            "HTTP_AUTHORIZATION": authz
        })
        self.assertEquals(authenticated_userid(req), "user1")
        authz = "Basic " + "user1:WRONG".encode("base64").strip()
        req = self._make_request({
            "HTTP_AUTHORIZATION": authz
        })
        self.assertEquals(authenticated_userid(req), None)

    def test_that_explicit_settings_are_not_overridden(self):
        # Create a new config with some explicit who-auth settings.
        config2 = pyramid.testing.setUp()
        config2.add_settings(self.DEFAULT_SETTINGS)
        config2.add_settings({
            "who.authenticators.plugins": "fakeauth",
            "who.identifiers.plugins": "fakeid",
            "who.challengers.plugins": "fakeid",
            "who.plugin.fakeauth.use":
                "mozsvc.tests.test_user:FakeAuthPlugin",
            "who.plugin.fakeid.use":
                "mozsvc.tests.test_user:FakeIdentifierPlugin",
        })
        config2.include("mozsvc.user.whoauth")
        config2.commit()
        # Now poke at it to see what has been overridden.
        policy = config2.registry.queryUtility(IAuthenticationPolicy)
        api_factory = policy.api_factory
        self.assertEquals(len(api_factory.authenticators), 1)
        self.assertEquals(api_factory.authenticators[0][1].__class__.__name__,
                          "FakeAuthPlugin")
        self.assertEquals(len(api_factory.identifiers), 1)
        self.assertEquals(api_factory.identifiers[0][1].__class__.__name__,
                          "FakeIdentifierPlugin")

    def test_graceful_handling_of_bad_auth_policy(self):
        # This just re-tests the functionality from mozvsc.user, making
        # sure that a non-repoze-who policy doesnt mess it up.
        config2 = pyramid.testing.setUp(autocommit=False)
        config2.add_settings(self.DEFAULT_SETTINGS)
        config2.include("mozsvc.user.whoauth")
        config2.set_authentication_policy(HeaderAuthenticationPolicy())
        config2.commit()
        request = self._make_request(factory=mozsvc.user.RequestWithUser)
        self.assertFalse(request.user)
        credentials = {"username": "user1", "password": "password1"}
        mozsvc.user.authenticate(request, credentials)
        self.assertEquals(request.user["username"], "user1")

    def test_graceful_handling_of_other_request_objects(self):
        authz = "Basic " + "user1:password1".encode("base64").strip()
        req = self._make_request({
            "HTTP_AUTHORIZATION": authz
        }, factory=pyramid.request.Request)
        # This makes the request available via get_current_request()
        self.config.begin(request=req)
        try:
            self.assertEquals(authenticated_userid(req), "user1")
        finally:
            self.config.end()
