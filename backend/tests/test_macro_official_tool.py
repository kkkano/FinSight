# -*- coding: utf-8 -*-
import backend.tools.macro_official as macro_official_mod


def test_search_official_macro_releases_parses_official_feed(monkeypatch):
    sample_xml = """
    <rss version="2.0">
      <channel>
        <item>
          <title>BLS CPI News Release</title>
          <link>https://www.bls.gov/news.release/cpi.nr0.htm</link>
          <description>Latest CPI update from BLS.</description>
          <pubDate>Tue, 11 Feb 2026 13:30:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """.strip()

    monkeypatch.setattr(
        macro_official_mod,
        "_OFFICIAL_FEEDS",
        (("bls", "BLS", "https://www.bls.gov/feed/bls_latest.rss"),),
    )
    monkeypatch.setattr(macro_official_mod, "_fetch_feed", lambda _url: sample_xml)

    rows = macro_official_mod.search_official_macro_releases("cpi inflation", max_results=5)

    assert rows
    assert rows[0].get("source") == "BLS"
    assert rows[0].get("domain") == "bls.gov"
    assert rows[0].get("is_official") is True


def test_get_official_macro_releases_fail_open_on_exception(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(macro_official_mod, "search_official_macro_releases", _raise)

    payload = macro_official_mod.get_official_macro_releases("cpi", max_results=5)

    assert payload.get("count") == 0
    assert str(payload.get("error") or "").startswith("fetch_failed:")
