"""The authorization request, and the scope promise screen 02 makes.

> least-privilege permissions - clear explanation of every requested scope -
> **separate authorization for sending emails**
> (08-ui-spec.md, screen 02 requirements)

That last clause is a product promise, so it gets a test rather than a
comment. If someone adds a send scope to the request, this fails.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from app.core.config import get_settings
from app.modules.providers.oauth.base import OAuthError
from app.modules.providers.oauth.google import (
    GMAIL_READONLY,
    REQUESTED_SCOPES,
    GoogleOAuthClient,
    missing_scopes,
)
from app.modules.providers.oauth.pkce import new_verifier, verifier_challenge


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr

    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "client-id.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", SecretStr("client-secret"))
    monkeypatch.setattr(
        settings, "google_redirect_uri", "http://localhost:8000/api/v1/auth/google/callback"
    )


def params_of(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


class TestRequestedScopes:
    def test_gmail_access_is_read_only(self) -> None:
        assert GMAIL_READONLY.endswith("gmail.readonly")
        assert GMAIL_READONLY in REQUESTED_SCOPES

    def test_no_scope_can_send_modify_or_delete_mail(self) -> None:
        forbidden = (
            "gmail.send",
            "gmail.modify",
            "gmail.compose",
            "gmail.insert",
            "mail.google.com",
        )
        for scope in REQUESTED_SCOPES:
            for capability in forbidden:
                assert capability not in scope, f"{scope} grants more than reading"

    def test_only_three_scopes_are_asked_for(self) -> None:
        assert len(REQUESTED_SCOPES) == 3


class TestAuthorizationUrl:
    def test_it_asks_google_for_exactly_the_declared_scopes(self, configured: None) -> None:
        url = GoogleOAuthClient().build_authorization_request().authorize_url
        assert params_of(url)["scope"].split() == list(REQUESTED_SCOPES)

    def test_it_uses_pkce_with_s256(self, configured: None) -> None:
        request = GoogleOAuthClient().build_authorization_request()
        params = params_of(request.authorize_url)
        assert params["code_challenge_method"] == "S256"
        assert params["code_challenge"] == verifier_challenge(request.code_verifier)

    def test_it_asks_for_offline_access(self, configured: None) -> None:
        """Without this there is no refresh token and the link dies in an hour."""
        assert (
            params_of(GoogleOAuthClient().build_authorization_request().authorize_url)[
                "access_type"
            ]
            == "offline"
        )

    def test_it_forces_consent_so_a_refresh_token_actually_arrives(self, configured: None) -> None:
        assert (
            params_of(GoogleOAuthClient().build_authorization_request().authorize_url)["prompt"]
            == "consent"
        )

    def test_incremental_authorization_is_off(self, configured: None) -> None:
        """Otherwise the grant quietly widens beyond what screen 02 described."""
        assert (
            params_of(GoogleOAuthClient().build_authorization_request().authorize_url)[
                "include_granted_scopes"
            ]
            == "false"
        )

    def test_each_request_gets_fresh_randomness(self, configured: None) -> None:
        first = GoogleOAuthClient().build_authorization_request()
        second = GoogleOAuthClient().build_authorization_request()
        assert first.state != second.state
        assert first.code_verifier != second.code_verifier

    def test_a_login_hint_is_passed_through_for_reconnect(self, configured: None) -> None:
        url = (
            GoogleOAuthClient()
            .build_authorization_request(login_hint="someone@example.com")
            .authorize_url
        )
        assert params_of(url)["login_hint"] == "someone@example.com"

    def test_it_refuses_to_build_a_url_without_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(get_settings(), "google_client_id", "")
        with pytest.raises(OAuthError, match="not configured"):
            GoogleOAuthClient().build_authorization_request()


class TestPkce:
    def test_the_verifier_length_is_inside_rfc_7636(self) -> None:
        assert 43 <= len(new_verifier()) <= 128

    def test_the_challenge_is_a_hash_not_the_verifier(self) -> None:
        verifier = new_verifier()
        assert verifier_challenge(verifier) != verifier

    def test_the_challenge_is_stable_for_a_given_verifier(self) -> None:
        verifier = new_verifier()
        assert verifier_challenge(verifier) == verifier_challenge(verifier)


class TestScopeValidation:
    def test_a_full_grant_is_missing_nothing(self) -> None:
        assert missing_scopes(" ".join(REQUESTED_SCOPES)) == ()

    def test_an_unticked_gmail_box_is_reported(self) -> None:
        """A consent screen lets someone decline a scope.

        The account then has to say what it is missing, rather than failing
        at the first sync with a 403 nobody can interpret.
        """
        partial = [s for s in REQUESTED_SCOPES if s != GMAIL_READONLY]
        assert GMAIL_READONLY in missing_scopes(partial)

    def test_it_accepts_either_a_list_or_a_space_separated_string(self) -> None:
        assert missing_scopes(list(REQUESTED_SCOPES)) == missing_scopes(" ".join(REQUESTED_SCOPES))

    def test_nothing_granted_means_everything_missing(self) -> None:
        assert len(missing_scopes(None)) == 2
