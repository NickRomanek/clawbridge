"""Tests for clawbridge.recorder.capture — keystroke coalescing."""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from clawbridge.recorder.capture import InputRecorder


class FakeKey:
    """Simulates pynput Key objects."""
    def __init__(self, char: str | None = None, name: str | None = None):
        if char is not None:
            self.char = char
        elif name is not None:
            self._name = name
            self.char = None
        else:
            self.char = None
    def __str__(self):
        if hasattr(self, "_name"):
            return f"Key.{self._name}"
        return str(self.char) if self.char else "Key.unknown"


@patch("clawbridge.recorder.capture._get_fg_window_title", return_value="Test Window")
class TestKeystrokeCoalescing:
    """Verify that key presses are coalesced correctly into type events."""

    def _make_recorder(self) -> InputRecorder:
        r = InputRecorder()
        r._recording = True
        r._start_time = 0.0
        return r

    def test_space_key_becomes_space_char(self, mock_title):
        """Space key should record as ' ' in text, not literal 'space'."""
        r = self._make_recorder()
        r._on_key_press(FakeKey(char="h"))
        r._on_key_press(FakeKey(char="i"))
        r._on_key_press(FakeKey(name="space"))
        r._on_key_press(FakeKey(char="u"))
        r._flush_key_buffer()

        type_events = [e for e in r._events if e["type"] == "type"]
        assert len(type_events) == 1
        assert type_events[0]["text"] == "hi u"

    def test_printable_chars_coalesce(self, mock_title):
        """Regular characters should coalesce into a single type event."""
        r = self._make_recorder()
        for ch in "hello":
            r._on_key_press(FakeKey(char=ch))
        r._flush_key_buffer()

        type_events = [e for e in r._events if e["type"] == "type"]
        assert len(type_events) == 1
        assert type_events[0]["text"] == "hello"

    def test_enter_breaks_coalescing(self, mock_title):
        """Enter should flush buffer and record as key event."""
        r = self._make_recorder()
        r._on_key_press(FakeKey(char="a"))
        r._on_key_press(FakeKey(name="enter"))
        r._on_key_press(FakeKey(char="b"))
        r._flush_key_buffer()

        assert r._events[0]["type"] == "type"
        assert r._events[0]["text"] == "a"
        assert r._events[1]["type"] == "key"
        assert r._events[1]["key"] == "enter"
        assert r._events[2]["type"] == "type"
        assert r._events[2]["text"] == "b"

    def test_unknown_special_key_recorded_as_key_event(self, mock_title):
        """Unknown special keys (e.g. f1) should become key events, not text."""
        r = self._make_recorder()
        r._on_key_press(FakeKey(char="x"))
        r._on_key_press(FakeKey(name="f1"))
        r._on_key_press(FakeKey(char="y"))
        r._flush_key_buffer()

        assert r._events[0]["type"] == "type"
        assert r._events[0]["text"] == "x"
        assert r._events[1]["type"] == "key"
        assert r._events[1]["key"] == "f1"
        assert r._events[2]["type"] == "type"
        assert r._events[2]["text"] == "y"

    def test_multiple_spaces_in_text(self, mock_title):
        """Multiple spaces should all be actual space characters."""
        r = self._make_recorder()
        r._on_key_press(FakeKey(char="a"))
        r._on_key_press(FakeKey(name="space"))
        r._on_key_press(FakeKey(name="space"))
        r._on_key_press(FakeKey(char="b"))
        r._flush_key_buffer()

        type_events = [e for e in r._events if e["type"] == "type"]
        assert len(type_events) == 1
        assert type_events[0]["text"] == "a  b"
