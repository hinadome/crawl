from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

TRACKING_QUERY_KEYS = frozenset(
    {
        "fbclid",
        "gclid",
        "gclsrc",
        "mc_cid",
        "mc_eid",
        "ref",
        "ref_src",
        "referrer",
    }
)
TRACKING_QUERY_PREFIXES = ("utm_",)

IGNORED_EXTENSIONS = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".zip",
    ".mp4",
    ".mp3",
    ".css",
    ".js",
    ".woff",
    ".woff2",
    ".ico",
)

AUTH_PATH_PREFIXES = (
    "/login",
    "/logout",
    "/signin",
    "/signup",
    "/sso",
    "/saml",
)

SKIP_SCHEMES = frozenset({"mailto", "javascript", "tel", "data", "ftp"})


def normalize_url(url: str, base: str | None = None) -> str:
    if base:
        url = urljoin(base, url)
    parsed = urlparse(url)
    fragmentless = parsed._replace(fragment="")
    scheme = (fragmentless.scheme or "https").lower()
    host = (fragmentless.hostname or "").lower()
    if not host:
        return urlunparse(fragmentless._replace(scheme=scheme, netloc=""))

    port = fragmentless.port
    if port and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        netloc = f"{host}:{port}"
    else:
        netloc = host

    path = fragmentless.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = ""

    query_pairs = []
    for key, value in parse_qsl(fragmentless.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in TRACKING_QUERY_KEYS:
            continue
        if any(lowered.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        query_pairs.append((key, value))
    query = urlencode(query_pairs, doseq=True)

    return urlunparse((scheme, netloc, path, "", query, ""))


def host_in_scope(host: str, seed_host: str, include_subdomains: bool) -> bool:
    host = host.lower()
    seed_host = seed_host.lower()
    if host == seed_host:
        return True
    if include_subdomains and host.endswith("." + seed_host):
        return True
    return False


def is_asset_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(IGNORED_EXTENSIONS)


def is_auth_path(url: str) -> bool:
    path = urlparse(url).path.lower()
    if not path.startswith("/"):
        path = "/" + path
    return any(path == prefix or path.startswith(prefix + "/") for prefix in AUTH_PATH_PREFIXES)


def should_enqueue(
    url: str,
    seed_host: str,
    include_subdomains: bool,
) -> bool:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme in SKIP_SCHEMES:
        return False
    if scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if not host_in_scope(host, seed_host, include_subdomains):
        return False
    if is_asset_url(url):
        return False
    if is_auth_path(url):
        return False
    return True
