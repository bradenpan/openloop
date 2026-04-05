"""Unit tests for gmail_client internal helpers.

Tests MIME parsing, HTML stripping, and header extraction functions.
No Google API calls are made.
"""

from __future__ import annotations

import base64

from backend.openloop.services.gmail_client import (
    _extract_header,
    _parse_message_body,
    _strip_html,
)


# ---------------------------------------------------------------------------
# _extract_header
# ---------------------------------------------------------------------------


class TestExtractHeader:
    def test_finds_header_by_name(self):
        headers = [
            {"name": "From", "value": "alice@example.com"},
            {"name": "To", "value": "bob@example.com"},
            {"name": "Subject", "value": "Test Subject"},
        ]
        assert _extract_header(headers, "Subject") == "Test Subject"
        assert _extract_header(headers, "From") == "alice@example.com"

    def test_case_insensitive_lookup(self):
        headers = [
            {"name": "Content-Type", "value": "text/html"},
        ]
        assert _extract_header(headers, "content-type") == "text/html"
        assert _extract_header(headers, "CONTENT-TYPE") == "text/html"

    def test_returns_none_for_missing_header(self):
        headers = [
            {"name": "From", "value": "alice@example.com"},
        ]
        assert _extract_header(headers, "Subject") is None

    def test_empty_headers_list(self):
        assert _extract_header([], "Subject") is None


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------


class TestStripHtml:
    def test_strips_basic_tags(self):
        html = "<p>Hello <b>world</b></p>"
        result = _strip_html(html)
        assert "Hello" in result
        assert "world" in result
        assert "<p>" not in result
        assert "<b>" not in result

    def test_strips_script_and_style(self):
        html = (
            "<html><head><style>body{color:red}</style></head>"
            "<body><script>alert('xss')</script>Hello</body></html>"
        )
        result = _strip_html(html)
        assert "alert" not in result
        assert "color:red" not in result
        assert "Hello" in result

    def test_br_to_newline(self):
        html = "Line 1<br>Line 2<br/>Line 3"
        result = _strip_html(html)
        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result

    def test_collapses_whitespace(self):
        html = "<p>Line 1</p>\n\n\n\n<p>Line 2</p>"
        result = _strip_html(html)
        assert "\n\n\n" not in result


# ---------------------------------------------------------------------------
# _parse_message_body
# ---------------------------------------------------------------------------


def _encode_body(text: str) -> str:
    """Base64url-encode text for Gmail payload simulation."""
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8").rstrip("=")


class TestParseMessageBody:
    def test_plain_text_message(self):
        payload = {
            "mimeType": "text/plain",
            "body": {"data": _encode_body("Hello, world!")},
        }
        result = _parse_message_body(payload)
        assert "Hello, world!" in result

    def test_multipart_prefers_plain_text(self):
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _encode_body("Plain text version")},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": _encode_body("<p>HTML version</p>")},
                },
            ],
        }
        result = _parse_message_body(payload)
        assert result == "Plain text version"

    def test_html_fallback_when_no_plain(self):
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": _encode_body("<p>Only HTML</p>")},
                },
            ],
        }
        result = _parse_message_body(payload)
        assert "Only HTML" in result
        assert "<p>" not in result  # HTML tags should be stripped

    def test_single_part_html_message(self):
        """Single-part message with text/html mime type (no parts array)."""
        payload = {
            "mimeType": "text/html",
            "body": {"data": _encode_body("<div>Single HTML body</div>")},
        }
        result = _parse_message_body(payload)
        assert "Single HTML body" in result
        assert "<div>" not in result

    def test_empty_payload(self):
        payload = {"mimeType": "multipart/mixed", "parts": []}
        result = _parse_message_body(payload)
        assert result == ""
