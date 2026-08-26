import base64
import unittest
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from plct_server.content.server import ConfigOptions
from plct_server.endpoints.auth import UiGate, authenticate, require_auth


class FakeServerContent:
    def __init__(self, **options):
        self.config_options = ConfigOptions(**options)


def with_config(**options):
    """Patch both call sites: the middleware and the dependency each fetch their own."""
    return patch("plct_server.endpoints.auth.get_server_content",
                 return_value=FakeServerContent(**options))


def basic(user: str, password: str) -> str:
    encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {encoded}"


class AuthenticateTests(unittest.TestCase):
    def test_recognises_each_credential(self):
        conf = ConfigOptions(api_key="secret", ui_password="letmein")
        self.assertEqual(authenticate(Headers({"X-Auth-Key": "secret"}), conf), "api-key")
        self.assertEqual(
            authenticate(Headers({"authorization": basic("tester", "letmein")}), conf),
            "ui-password")

    def test_user_name_is_not_checked(self):
        """One shared password, so there is no name to look up -- any name is accepted."""
        conf = ConfigOptions(ui_password="letmein")
        self.assertIsNotNone(authenticate(Headers({"authorization": basic("", "letmein")}), conf))

    def test_rejects_wrong_absent_and_malformed_credentials(self):
        conf = ConfigOptions(api_key="secret", ui_password="letmein")
        for headers in [{},
                        {"X-Auth-Key": "wrong"},
                        {"authorization": basic("tester", "wrong")},
                        {"authorization": "Bearer secret"},
                        {"authorization": "Basic not-base64!!"},
                        {"authorization": "Basic " + base64.b64encode(b"nocolon").decode()}]:
            with self.subTest(headers=headers):
                self.assertIsNone(authenticate(Headers(headers), conf))

    def test_an_unset_secret_never_matches(self):
        """Otherwise an empty header would authenticate against an unconfigured key."""
        conf = ConfigOptions()
        self.assertIsNone(authenticate(Headers({"X-Auth-Key": ""}), conf))
        self.assertIsNone(authenticate(Headers({"authorization": basic("u", "")}), conf))


def gated_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(UiGate)

    @app.get("/app/")
    async def page():
        return {"page": True}

    @app.get("/api/chat", dependencies=[Depends(require_auth)])
    async def chat():
        return {"chat": True}

    return app


class UiGateTests(unittest.TestCase):
    def test_open_site_when_no_password_is_configured(self):
        with with_config():
            client = TestClient(gated_app())
            self.assertEqual(client.get("/app/").status_code, 200)

    def test_challenges_every_path_when_the_password_is_set(self):
        with with_config(ui_password="letmein"):
            client = TestClient(gated_app())
            response = client.get("/app/")
            self.assertEqual(response.status_code, 401)
            self.assertIn("Basic", response.headers["WWW-Authenticate"])

    def test_basic_credentials_open_the_site(self):
        with with_config(ui_password="letmein"):
            client = TestClient(gated_app())
            response = client.get("/app/", headers={"authorization": basic("t", "letmein")})
            self.assertEqual(response.status_code, 200)

    def test_the_api_key_is_never_challenged(self):
        """The platform holds a key, not a password: it must not meet a Basic prompt."""
        with with_config(api_key="secret", ui_password="letmein"):
            client = TestClient(gated_app())
            response = client.get("/api/chat", headers={"X-Auth-Key": "secret"})
            self.assertEqual(response.status_code, 200)


class RequireAuthTests(unittest.TestCase):
    def test_chat_is_open_when_no_api_key_is_configured(self):
        """A local `plct-serve` has no key and must stay usable."""
        with with_config():
            client = TestClient(gated_app())
            self.assertEqual(client.get("/api/chat").status_code, 200)

    def test_chat_needs_a_credential_once_an_api_key_is_configured(self):
        with with_config(api_key="secret"):
            client = TestClient(gated_app())
            self.assertEqual(client.get("/api/chat").status_code, 401)
            self.assertEqual(
                client.get("/api/chat", headers={"X-Auth-Key": "secret"}).status_code, 200)

    def test_a_gated_tester_reaches_chat_without_the_api_key(self):
        """The whole point of the temporary gate: the browser has no key to send."""
        with with_config(api_key="secret", ui_password="letmein"):
            client = TestClient(gated_app())
            response = client.get("/api/chat", headers={"authorization": basic("t", "letmein")})
            self.assertEqual(response.status_code, 200)

    def test_chat_stays_shut_when_the_gate_is_removed(self):
        """Unsetting `ui_password` at the end of testing must not reopen the endpoint."""
        with with_config(api_key="secret"):
            client = TestClient(gated_app())
            response = client.get("/api/chat", headers={"authorization": basic("t", "letmein")})
            self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
