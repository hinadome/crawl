from __future__ import annotations

from crawler.normalize import normalize_url, should_enqueue


def load_url_file(path: str) -> list[str]:
    urls: list[str] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


def collect_target_urls(
    *,
    urls: list[str] | None = None,
    url_file: str | None = None,
) -> list[str]:
    collected: list[str] = []
    for raw in urls or []:
        collected.append(raw)
    if url_file:
        collected.extend(load_url_file(url_file))
    # preserve order, drop duplicates after normalize
    seen: set[str] = set()
    result: list[str] = []
    for raw in collected:
        normalized = normalize_url(raw)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def filter_in_scope(
    urls: list[str],
    seed_host: str,
    include_subdomains: bool,
) -> tuple[list[str], list[str]]:
    accepted: list[str] = []
    rejected: list[str] = []
    for url in urls:
        if should_enqueue(url, seed_host, include_subdomains):
            accepted.append(url)
        else:
            rejected.append(url)
    return accepted, rejected
