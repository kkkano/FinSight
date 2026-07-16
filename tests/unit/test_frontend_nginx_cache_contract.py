from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NGINX_CONFIG = ROOT / "frontend" / "nginx.conf"


def test_service_worker_release_files_are_never_immutable() -> None:
    config = NGINX_CONFIG.read_text(encoding="utf-8")
    release_location = (
        "location ~ ^/(?:sw\\.js|registerSW\\.js|manifest\\.webmanifest)$"
    )

    release_offset = config.index(release_location)
    static_offset = config.index("location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff2?)$")
    release_block_end = config.index("\n    }", release_offset)
    release_block = config[release_offset:release_block_end]

    assert release_offset < static_offset
    assert 'Cache-Control "no-cache, no-store, must-revalidate" always' in release_block
    assert "expires off;" in release_block


def test_index_html_is_never_cached() -> None:
    config = NGINX_CONFIG.read_text(encoding="utf-8")
    index_offset = config.index("location = /index.html")
    index_block_end = config.index("\n    }", index_offset)
    index_block = config[index_offset:index_block_end]

    assert 'Cache-Control "no-cache, no-store, must-revalidate" always' in index_block
    assert "expires off;" in index_block
