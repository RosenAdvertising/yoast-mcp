"""Real configuration-loader regression for the offline verify command."""

import pytest

from yoast_mcp import config, setup


@pytest.mark.parametrize("variable", ["WORDPRESS_SITE_URL"])
@pytest.mark.parametrize(
    "url", ["https://[invalid", "https://example.invalid:bad", "https://example.invalid:99999"]
)
def test_verify_malformed_url(monkeypatch, capsys, variable, url):
    for key, value in {
        "WORDPRESS_SITE_URL": "https://example.invalid",
        "WORDPRESS_USERNAME": "synthetic",
        "WORDPRESS_APPLICATION_PASSWORD": "synthetic",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("ELITE3E_AUDIENCE", raising=False)
    monkeypatch.setenv(variable, url)
    with pytest.raises(config.ConfigurationError, match=variable):
        config.Settings.from_env()
    assert setup.verify() == 2
    output = capsys.readouterr().err
    assert "yoast-mcp-setup" in output
    assert variable in output
    assert "Traceback" not in output
    assert url not in output
