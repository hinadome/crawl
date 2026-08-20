# Main-content extraction — task list

## Slice 1 — extract core

- [x] Add Trafilatura dependency
- [x] `extract_main_html(raw, mode, selector)` with Trafilatura → semantic → chrome-strip → full fallback
- [x] Wire into `render_content`
- [x] Keep `extract_hrefs` on full HTML

## Slice 2 — sinks + CLI

- [x] `FilesystemSink` / `SqliteSink` take `content_mode` and `content_selector`
- [x] `--content` / `--content-selector` on both crawl CLIs
- [x] Validate: `selector` mode requires `--content-selector`

## Slice 3 — tests and docs

- [x] Fixture: nav + main; `main` drops nav text; `full` keeps it; selector works
- [x] Short main-extract falls back when page has substantial text
- [x] README + CHANGELOG
- [x] Mark plan implemented
