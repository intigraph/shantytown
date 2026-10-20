"""Native helper translation must not retain an overriding credential."""
import pytest

from shantytown.provision import ProvisionError, _codex_servers


def test_helper_uses_native_field_and_preserves_non_auth_headers():
    original = {"type": "http", "url": "http://example.invalid/mcp",
                "headersHelper": "read-volatile-header",
                "headers": {"authorization": "synthetic", "X-Control": "yes"},
                "bearer_token_env_var": "SYNTHETIC_TOKEN"}
    got = _codex_servers({"probe": original})["probe"]
    assert got == {"url": original["url"],
                   "http_headers_helper": "read-volatile-header",
                   "http_headers": {"X-Control": "yes"}}
    assert original["headers"]["authorization"] == "synthetic"


@pytest.mark.parametrize("helper", ["", " ", [], 4])
def test_invalid_helper_refuses(helper):
    with pytest.raises(ProvisionError, match="nonempty command"):
        _codex_servers({"probe": {"headersHelper": helper}})


def test_unselected_server_keeps_legacy_shared_behavior():
    assert _codex_servers({"probe": {"headers": {"Authorization": "synthetic"}}}) == {
        "probe": {"http_headers": {"Authorization": "synthetic"}}}
