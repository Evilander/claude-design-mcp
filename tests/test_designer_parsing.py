"""Unit tests for the designer's response parser.

These tests don't hit the API — they exercise ``_extract_html_block`` and
``_extract_json_block`` directly, plus the API-error translation helper.
"""

from __future__ import annotations

import pytest

from claude_design.designer import (
    _extract_api_message,
    _extract_html_block,
    _extract_json_block,
)


class _FakeStatusError:
    def __init__(self, body=None, message=None, status_code=400):
        self.body = body
        self.message = message
        self.status_code = status_code


GOOD_RESPONSE = """\
Here you go:

```html
<!doctype html>
<html><body>hi</body></html>
```

```json
{"title": "hi", "palette": ["#000", "#fff"]}
```
"""


def test_extract_html_block_finds_fenced_html():
    assert "<!doctype html>" in _extract_html_block(GOOD_RESPONSE)


def test_extract_json_block_returns_last_block():
    text = "```json\n{\"a\": 1}\n```\nstuff\n```json\n{\"b\": 2}\n```"
    assert _extract_json_block(text) == '{"b": 2}'


def test_extract_html_block_falls_back_to_doctype():
    text = "intro\n<!doctype html>\n<html><body>x</body></html>\noutro"
    assert _extract_html_block(text) and "<body>x</body>" in _extract_html_block(text)


def test_extract_html_block_returns_none_when_missing():
    assert _extract_html_block("no code here") is None


def test_extract_json_block_returns_none_when_missing():
    assert _extract_json_block("no fences") is None


def test_extract_api_message_pulls_nested_message():
    err = _FakeStatusError(body={"error": {"message": "credit balance too low"}})
    assert _extract_api_message(err) == "credit balance too low"


def test_extract_api_message_falls_back_to_attribute():
    err = _FakeStatusError(body={}, message="fallback")
    assert _extract_api_message(err) == "fallback"


def test_extract_api_message_returns_none_when_blank():
    err = _FakeStatusError(body=None, message=None)
    assert _extract_api_message(err) is None


def test_html_fence_is_case_insensitive():
    text = "```HTML\n<!doctype html><html></html>\n```"
    assert _extract_html_block(text) is not None


def test_json_fence_is_case_insensitive():
    text = "```JSON\n{\"x\": 1}\n```"
    assert _extract_json_block(text) == '{"x": 1}'
