from app.models.schemas import OutputFormat
from app.services.cleaner import clean

SAMPLE = """
<html lang="en">
  <head>
    <title>Test Page</title>
    <meta name="description" content="A test page.">
  </head>
  <body>
    <nav><a href="/about">About</a></nav>
    <article>
      <h1>Hello World</h1>
      <p>This is the main content of the page.</p>
      <a href="https://example.com/deep">Deep link</a>
    </article>
    <script>console.log('noise')</script>
  </body>
</html>
"""


def test_metadata_and_markdown():
    res = clean(
        SAMPLE,
        url="https://example.com/",
        status_code=200,
        formats=[OutputFormat.markdown, OutputFormat.links],
    )
    assert res.metadata.title == "Test Page"
    assert res.metadata.description == "A test page."
    assert res.metadata.status_code == 200
    assert "Hello World" in (res.markdown or "")
    assert "console.log" not in (res.markdown or "")  # script stripped


def test_links_resolved_absolute():
    res = clean(SAMPLE, url="https://example.com/", status_code=200,
                formats=[OutputFormat.links])
    assert "https://example.com/about" in res.links
    assert "https://example.com/deep" in res.links
