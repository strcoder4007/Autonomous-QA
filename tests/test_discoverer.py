"""Tests for the spec discovery module."""

import httpx
import pytest
import respx

from swaggertest.discoverer import discover_spec_url

SWAGGER_UI_URL = "https://api.example.com/swagger-ui/index.html"

SAMPLE_SPEC = '{"openapi": "3.0.0", "info": {"title": "Test", "version": "1.0"}, "paths": {}}'

SWAGGER_HTML_WITH_BUNDLE = """
<html>
<body>
<script>
const ui = SwaggerUIBundle({
    url: "/v3/api-docs",
    dom_id: '#swagger-ui'
})
</script>
</body>
</html>
"""

SWAGGER_HTML_NO_URL = "<html><body>No spec here</body></html>"


@respx.mock
def test_discover_from_swagger_ui_bundle():
    respx.get(SWAGGER_UI_URL).mock(return_value=httpx.Response(200, text=SWAGGER_HTML_WITH_BUNDLE))
    respx.get("https://api.example.com/v3/api-docs").mock(return_value=httpx.Response(200, text=SAMPLE_SPEC))

    result = discover_spec_url(SWAGGER_UI_URL)
    assert result == "https://api.example.com/v3/api-docs"


@respx.mock
def test_discover_falls_back_to_default_paths():
    respx.get(SWAGGER_UI_URL).mock(return_value=httpx.Response(200, text=SWAGGER_HTML_NO_URL))
    # All default paths return 404 except /swagger.json
    respx.get("https://api.example.com/v3/api-docs").mock(return_value=httpx.Response(404))
    respx.get("https://api.example.com/v2/api-docs").mock(return_value=httpx.Response(404))
    respx.get("https://api.example.com/swagger.json").mock(return_value=httpx.Response(200, text=SAMPLE_SPEC))

    result = discover_spec_url(SWAGGER_UI_URL)
    assert result == "https://api.example.com/swagger.json"


@respx.mock
def test_discover_raises_when_no_spec_found():
    respx.get(SWAGGER_UI_URL).mock(return_value=httpx.Response(200, text=SWAGGER_HTML_NO_URL))
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(404))

    with pytest.raises(RuntimeError, match="Could not locate the OpenAPI spec"):
        discover_spec_url(SWAGGER_UI_URL)
