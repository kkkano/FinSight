import json

from backend.services.conversation_store import jsonb_text

NUL, BACKSLASH = chr(0), chr(92)


def test_jsonb_text_removes_nul_recursively_and_keeps_other_text():
    value = {"content": "营收" + NUL + "增长", "key" + NUL: [NUL + "a", ("b" + NUL,)], "n": 1.5, "flag": True}
    encoded = jsonb_text(value)
    assert NUL not in encoded and BACKSLASH + "u0000" not in encoded
    assert json.loads(encoded) == {"content": "营收增长", "key": ["a", ["b"]], "n": 1.5, "flag": True}


def test_jsonb_text_preserves_literal_backslash_sequences_and_stringifies_unknown_objects():
    class Odd:
        def __str__(self):
            return "x" + NUL + "y"

    literal = "C:" + BACKSLASH + "u0000dir"
    encoded = jsonb_text({"path": literal, "odd": Odd()})
    assert json.loads(encoded) == {"path": literal, "odd": "xy"}
