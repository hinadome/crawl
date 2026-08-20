from crawler.extract import extract_hrefs, extract_main_html, html_to_markdown, render_content

PAGE = """
<html>
<head><title>Docs</title></head>
<body>
<nav>
  <a href="/home">Home</a>
  <a href="/about">About</a>
  <p>Navigation menu UniqueNavToken should not appear in main mode</p>
</nav>
<header><p>Site header chrome UniqueHeaderToken</p></header>
<main>
  <h1>Install Guide</h1>
  <p>Install the acme widget with pip install acme. This paragraph is long enough that main extraction should keep it as the focused body content for RAG and reading.</p>
  <p>Second paragraph with more UniqueBodyToken detail about configuration and usage.</p>
  <a href="/install/next">Next</a>
</main>
<footer><p>Copyright UniqueFooterToken</p></footer>
</body>
</html>
"""


def test_main_mode_drops_nav_keeps_body():
    html = extract_main_html(PAGE, content_mode="main")
    text = html_to_markdown(html)
    assert "UniqueBodyToken" in text
    assert "Install Guide" in text or "Install" in text
    assert "UniqueNavToken" not in text
    assert "UniqueFooterToken" not in text


def test_full_mode_keeps_nav():
    html = extract_main_html(PAGE, content_mode="full")
    text = html_to_markdown(html)
    assert "UniqueNavToken" in text
    assert "UniqueBodyToken" in text


def test_selector_mode():
    html = extract_main_html(
        PAGE,
        content_mode="selector",
        content_selector="main",
    )
    text = html_to_markdown(html)
    assert "UniqueBodyToken" in text
    assert "UniqueNavToken" not in text


def test_hrefs_still_see_nav_links():
    hrefs = extract_hrefs(PAGE, "https://example.com/docs")
    assert any(h.endswith("/home") for h in hrefs)
    assert any(h.endswith("/about") for h in hrefs)
    assert any(h.endswith("/install/next") for h in hrefs)


def test_render_markdown_uses_main_by_default():
    content, _ = render_content("markdown", "https://example.com/docs", PAGE, "Docs")
    assert "UniqueBodyToken" in content
    assert "UniqueNavToken" not in content


def test_short_extract_falls_back_when_page_is_rich():
    # Tiny article region but large page body → semantic/chrome fallback should still yield body
    weird = """
    <html><body>
    <nav>""" + ("nav link " * 40) + """</nav>
    <div class="content">
      <h1>Real Title</h1>
      <p>""" + ("Important body sentence about widgets. " * 30) + """</p>
    </div>
    <article><p>x</p></article>
    </body></html>
    """
    html = extract_main_html(weird, content_mode="main")
    text = html_to_markdown(html)
    assert "Important body sentence" in text or "Real Title" in text
