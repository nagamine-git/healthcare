"""freee_client: OAuth トークンの構築・鮮度判定 (純ロジック部分)。"""

from __future__ import annotations

import json
import time
from unittest.mock import patch

from app.config import Settings
from app.integrations import freee_client as fc


def _settings(temp_data_dir) -> Settings:
    return Settings(
        app_data_dir=temp_data_dir,
        freee_client_id="CID123",
        freee_client_secret="dummy",  # テスト用ダミー値
        freee_redirect_base="https://healthcare.tailcda87f.ts.net",
    )


def test_redirect_uri_matches_registered_callback(temp_data_dir):
    s = _settings(temp_data_dir)
    assert fc.redirect_uri(s) == "https://healthcare.tailcda87f.ts.net/admin/freee/oauth/callback"


def test_authorize_url_includes_client_id_and_redirect_uri(temp_data_dir):
    s = _settings(temp_data_dir)
    url = fc.authorize_url(s)
    assert url.startswith(fc.AUTHORIZE_URL)
    assert "client_id=CID123" in url
    assert "response_type=code" in url
    # redirect_uri は URL エンコードされて含まれる (: と / がエンコードされる)
    assert "redirect_uri=https%3A%2F%2Fhealthcare.tailcda87f.ts.net" in url


def test_authorize_url_includes_state_when_given(temp_data_dir):
    s = _settings(temp_data_dir)
    url = fc.authorize_url(s, state="xyz789")
    assert "state=xyz789" in url


def test_authorize_url_omits_state_param_when_not_given(temp_data_dir):
    s = _settings(temp_data_dir)
    assert "state=" not in fc.authorize_url(s)


def test_generate_state_is_verifiable_once(temp_data_dir):
    s = _settings(temp_data_dir)
    state = fc.generate_state(settings=s)
    assert fc.verify_state(state, settings=s) is True
    # single-use: 2回目は既に消費済みなので拒否
    assert fc.verify_state(state, settings=s) is False


def test_verify_state_rejects_wrong_value(temp_data_dir):
    s = _settings(temp_data_dir)
    fc.generate_state(settings=s)
    assert fc.verify_state("attacker-guessed-value", settings=s) is False


def test_verify_state_rejects_when_never_issued(temp_data_dir):
    s = _settings(temp_data_dir)
    assert fc.verify_state("whatever", settings=s) is False


def test_verify_state_rejects_when_expired(temp_data_dir):
    s = _settings(temp_data_dir)
    state = fc.generate_state(settings=s)
    stale = json.loads(fc._state_path(s).read_text())
    stale["created_at"] = time.time() - fc.STATE_TTL_SECONDS - 1
    fc._state_path(s).write_text(json.dumps(stale))
    assert fc.verify_state(state, settings=s) is False


def test_has_token_false_when_never_authorized(temp_data_dir):
    s = _settings(temp_data_dir)
    with patch("app.integrations.freee_client.get_settings", return_value=s):
        assert fc.has_token() is False


def test_get_valid_access_token_none_without_token_file(temp_data_dir):
    s = _settings(temp_data_dir)
    with patch("app.integrations.freee_client.get_settings", return_value=s):
        assert fc.get_valid_access_token() is None


def test_get_valid_access_token_returns_cached_when_fresh(temp_data_dir):
    s = _settings(temp_data_dir)
    fc.token_path(s).write_text(json.dumps({
        "access_token": "fresh-token", "refresh_token": "r1",
        "expires_in": 21600, "obtained_at": time.time(),
    }))
    with patch("app.integrations.freee_client.get_settings", return_value=s), \
         patch("app.integrations.freee_client._refresh") as mock_refresh:
        token = fc.get_valid_access_token()
    assert token == "fresh-token"
    mock_refresh.assert_not_called()


def test_get_valid_access_token_refreshes_when_expired(temp_data_dir):
    s = _settings(temp_data_dir)
    fc.token_path(s).write_text(json.dumps({
        "access_token": "old-token", "refresh_token": "r1",
        "expires_in": 60, "obtained_at": time.time() - 3600,
    }))
    with patch("app.integrations.freee_client.get_settings", return_value=s), \
         patch("app.integrations.freee_client._refresh", return_value={
             "access_token": "new-token", "refresh_token": "r2", "expires_in": 21600,
         }) as mock_refresh:
        token = fc.get_valid_access_token()
    assert token == "new-token"
    mock_refresh.assert_called_once()


def test_exchange_code_persists_tokens(temp_data_dir):
    s = _settings(temp_data_dir)
    fake_response = {"access_token": "a1", "refresh_token": "r1", "expires_in": 21600}
    with patch("httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value.json.return_value = fake_response
        mock_client.post.return_value.raise_for_status.return_value = None
        result = fc.exchange_code("auth-code-xyz", settings=s)
    assert result == fake_response
    saved = json.loads(fc.token_path(s).read_text())
    assert saved["access_token"] == "a1"
    assert "obtained_at" in saved
