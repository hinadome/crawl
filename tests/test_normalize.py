from crawler.normalize import (
    host_in_scope,
    is_auth_path,
    normalize_url,
    should_enqueue,
)


def test_strips_fragment_and_tracking_params():
    url = "https://Example.COM:443/a/b/?utm_source=x&gclid=1&keep=yes#section"
    assert normalize_url(url) == "https://example.com/a/b?keep=yes"


def test_trailing_slash_non_root():
    assert normalize_url("https://example.com/docs/") == "https://example.com/docs"


def test_suffix_domain_is_not_in_scope():
    assert not host_in_scope("notexample.com", "example.com", include_subdomains=True)
    assert not host_in_scope("evil-docs.example.com", "docs.example.com", include_subdomains=True)
    assert host_in_scope("docs.example.com", "example.com", include_subdomains=True)
    assert not host_in_scope("docs.example.com", "example.com", include_subdomains=False)


def test_auth_prefix_does_not_drop_author():
    assert is_auth_path("https://example.com/login")
    assert is_auth_path("https://example.com/login/next")
    assert not is_auth_path("https://example.com/author")
    assert not is_auth_path("https://example.com/authorization-guide")


def test_should_enqueue_filters():
    seed = "example.com"
    assert should_enqueue("https://example.com/page", seed, False)
    assert not should_enqueue("https://notexample.com/page", seed, False)
    assert not should_enqueue("https://example.com/file.pdf", seed, False)
    assert not should_enqueue("mailto:hi@example.com", seed, False)
    assert not should_enqueue("https://example.com/logout", seed, False)
