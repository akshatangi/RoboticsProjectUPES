import pytest

from teleop.protocol import (LineBuffer, ProtocolError, decode, encode, make_cmd, parse_command,
                             validate_cmd)


def test_parse_with_defaults():
    assert parse_command("move 1.5") == {"cmd": "move", "args": {"dist": 1.5, "speed": 0.3}}
    assert parse_command("GOTO 2 -1 0.5")["args"] == {"x": 2.0, "y": -1.0, "speed": 0.5}
    assert parse_command("  stop  ") == {"cmd": "stop", "args": {}}
    assert parse_command("vel 0.2 -30")["args"] == {"v": 0.2, "w": -30.0}


@pytest.mark.parametrize("line,fragment", [
    ("", "empty"),
    ("fly 3", "unknown command"),
    ("move", "needs <dist>"),
    ("move x", "must be a number"),
    ("move 1 2 3", "at most 2"),
    ("turn 90 -5", "must be positive"),
    ("move nan", "finite"),
])
def test_parse_errors(line, fragment):
    with pytest.raises(ProtocolError, match=fragment):
        parse_command(line)


def test_encode_decode_round_trip():
    msg = make_cmd(3, "goto", {"x": 1.0, "y": 2.0}, t=10.0)
    assert decode(encode(msg)) == msg
    assert b"\n" not in encode(msg)


@pytest.mark.parametrize("raw", [b"not json", b"[1,2]", b'{"no_type": 1}', b"\xff\xfe"])
def test_decode_rejects_garbage(raw):
    with pytest.raises(ProtocolError):
        decode(raw)


def test_line_buffer_handles_split_and_merged_messages():
    buf = LineBuffer()
    assert buf.feed(b'{"type":"a"}\n{"ty') == [b'{"type":"a"}']
    assert buf.feed(b'pe":"b"}\n\n{"type":"c"}\n') == [b'{"type":"b"}', b'{"type":"c"}']
    assert buf.feed(b"") == []


def test_line_buffer_limits_length():
    buf = LineBuffer()
    with pytest.raises(ProtocolError):
        buf.feed(b"x" * (LineBuffer.MAX_LINE + 1))


def test_validate_cmd():
    assert validate_cmd(make_cmd(1, "turn", {"angle": 45})) == {"angle": 45.0, "rate": 60.0}
    with pytest.raises(ProtocolError):
        validate_cmd({"type": "cmd", "seq": 1, "cmd": "rm", "args": {}})
    with pytest.raises(ProtocolError):
        validate_cmd({"type": "cmd", "seq": "1", "cmd": "stop", "args": {}})
    with pytest.raises(ProtocolError):
        validate_cmd({"type": "cmd", "seq": 1, "cmd": "goto", "args": {"x": 1}})
    with pytest.raises(ProtocolError):
        validate_cmd({"type": "cmd", "seq": 1, "cmd": "move", "args": {"dist": "1; rm -rf"}})
