from types import SimpleNamespace

import pytest

from backend.tools import web


def _minimal_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>stream\n" + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _response(body: bytes, content_type: str, url="https://www.example.com/report.pdf"):
    return SimpleNamespace(url=url, headers={"Content-Type": content_type}, content=body,
                           text=body.decode("latin-1"), raise_for_status=lambda: None)


@pytest.fixture
def fetch(monkeypatch):
    monkeypatch.setattr(web, "is_safe_url", lambda url: True)
    def install(response):
        monkeypatch.setattr(web.requests, "get", lambda *args, **kwargs: response)
        return web.fetch_url_document("https://www.example.com/report.pdf", max_length=2000)
    return install


@pytest.mark.parametrize("content_type", ["application/pdf", "application/octet-stream"])
def test_pdf_text_is_extracted_instead_of_raw_bytes(fetch, content_type):
    doc = fetch(_response(_minimal_pdf("Revenue grew 15 percent"), content_type))
    assert "Revenue grew 15 percent" in doc["content"]
    assert "%PDF" not in doc["content"] and chr(0) not in doc["content"]
    assert doc["title"] == "report.pdf" and doc["source"] == "www.example.com"


def test_non_text_binary_is_not_returned_as_content(fetch):
    assert fetch(_response(b"\x89PNG\r\n\x1a\n" + bytes(range(256)), "image/png")) is None


def test_html_path_is_unchanged(fetch):
    html = b"<html><head><title>Q2</title></head><body><article>Net income rose</article></body></html>"
    doc = fetch(_response(html, "text/html; charset=utf-8", url="https://www.example.com/q2"))
    assert doc["title"] == "Q2" and "Net income rose" in doc["content"]
