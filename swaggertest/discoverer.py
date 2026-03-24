"""Phase 1: Scrape Swagger UI HTML to discover the underlying OpenAPI spec URL."""

from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

# Common default spec paths to probe when HTML scraping fails.
DEFAULT_SPEC_PATHS = [
    "/v3/api-docs",
    "/v2/api-docs",
    "/swagger.json",
    "/openapi.json",
    "/openapi.yaml",
]


def discover_spec_url(swagger_ui_url: str, *, client: httpx.Client | None = None) -> str:
    """Discover the raw OpenAPI spec URL from a Swagger UI page.

    Raises ``RuntimeError`` if the spec cannot be located.
    """
    own_client = client is None
    if own_client:
        client = httpx.Client(follow_redirects=True, timeout=15)

    tried: list[str] = []

    try:
        resp = client.get(swagger_ui_url)
        resp.raise_for_status()
        html = resp.text

        # Strategy 1: look for url: "..." inside SwaggerUIBundle(...) or similar JS config.
        match = re.search(r"""SwaggerUIBundle\s*\(\s*\{[^}]*?url\s*:\s*["']([^"']+)["']""", html, re.DOTALL)
        if not match:
            match = re.search(r"""url\s*:\s*["']([^"']+\.(?:json|yaml|yml))["']""", html)
        if match:
            spec_url = _resolve(swagger_ui_url, match.group(1))
            tried.append(spec_url)
            if _is_spec(client, spec_url):
                return spec_url

        # Strategy 2: <meta name="swagger-config" ...> or configUrl pattern
        soup = BeautifulSoup(html, "html.parser")
        meta = soup.find("meta", attrs={"name": "swagger-config"})
        if meta and meta.get("content"):
            config_url = _resolve(swagger_ui_url, meta["content"])
            tried.append(config_url)
            config_resp = client.get(config_url)
            if config_resp.is_success:
                try:
                    config_data = config_resp.json()
                    if "url" in config_data:
                        spec_url = _resolve(swagger_ui_url, config_data["url"])
                        tried.append(spec_url)
                        if _is_spec(client, spec_url):
                            return spec_url
                except Exception:
                    pass

        # Strategy 3: configUrl in JS
        config_match = re.search(r"""configUrl\s*:\s*["']([^"']+)["']""", html)
        if config_match:
            config_url = _resolve(swagger_ui_url, config_match.group(1))
            tried.append(config_url)
            config_resp = client.get(config_url)
            if config_resp.is_success:
                try:
                    config_data = config_resp.json()
                    if "url" in config_data:
                        spec_url = _resolve(swagger_ui_url, config_data["url"])
                        tried.append(spec_url)
                        if _is_spec(client, spec_url):
                            return spec_url
                except Exception:
                    pass

        # Strategy 4: probe well-known default paths.
        for path in DEFAULT_SPEC_PATHS:
            spec_url = _resolve(swagger_ui_url, path)
            tried.append(spec_url)
            if _is_spec(client, spec_url):
                return spec_url

        raise RuntimeError(
            "ERROR: Could not locate the OpenAPI spec from the provided Swagger UI URL.\n"
            f"Tried patterns: {tried}\n"
            "Please verify the URL or check if the spec endpoint requires authentication."
        )
    finally:
        if own_client:
            client.close()


def _resolve(base: str, url: str) -> str:
    if url.startswith(("http://", "https://")):
        return url
    return urljoin(base, url)


def _is_spec(client: httpx.Client, url: str) -> bool:
    """Return True if *url* looks like a valid OpenAPI spec."""
    try:
        resp = client.get(url)
        if not resp.is_success:
            return False
        text = resp.text.strip()
        # Quick heuristic: contains openapi or swagger key
        return any(kw in text[:2000].lower() for kw in ('"openapi"', "'openapi'", '"swagger"', "'swagger'", "openapi:", "swagger:"))
    except httpx.HTTPError:
        return False
