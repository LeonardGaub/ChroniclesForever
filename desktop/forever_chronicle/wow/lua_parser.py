"""Safe parser for WoW SavedVariables files.

SavedVariables are Lua source files of the form ``Name = <value>``. This parser accepts only
literal data (tables, strings, numbers, booleans, nil) and comments. It never executes code:
anything else, such as a function call or an operator, is rejected with :class:`LuaParseError`.

Lua tables become Python lists when their keys are exactly 1..n, otherwise dicts.
"""

from __future__ import annotations

import re
from typing import Any

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_DEPTH = 64

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(
    r"-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|inf|nan)"
)
_LONG_BRACKET = re.compile(r"\[(=*)\[")
# Whitespace and line comments (not "--[[" long comments) in one match; long comments are handled in skip().
_SPACE = re.compile(r"(?:[ \t\r\n\ufeff]+|--(?!\[=*\[)[^\n]*)*")
_SKIP_START = frozenset(" \t\r\n\ufeff-")
_KEYWORDS = {"true": True, "false": False, "nil": None}
_ESCAPES = {"n": 10, "t": 9, "r": 13, "a": 7, "b": 8, "f": 12, "v": 11,
            "\\": 92, '"': 34, "'": 39, "\n": 10}
# A run of ordinary characters inside a string: up to the next quote, backslash or newline.
_STRING_RUN = {'"': re.compile(r'[^"\\\n]*'), "'": re.compile(r"[^'\\\n]*")}
# A string body whose escapes are all one-character ones from _ESCAPES (\n, \", \\, ...). Each of them gives one
# ASCII character, so such a body can be unescaped as text, without going through bytes.
_SIMPLE_BODY = {q: re.compile(rf"(?:[^{q}\\\n]+|\\[ntrabfv\\\"'\n])*") for q in "\"'"}
_SIMPLE_ESCAPES = [("\\" + k, chr(v)) for k, v in _ESCAPES.items() if k != "\\"]


class LuaParseError(ValueError):
    """Raised for malformed, truncated or non-literal input."""

    def __init__(self, message: str, text: str = "", pos: int = 0):
        line = text.count("\n", 0, pos) + 1
        col = pos - (text.rfind("\n", 0, pos) + 1) + 1
        super().__init__(f"{message} (line {line}, column {col})")
        self.line = line
        self.column = col


def parse_saved_variables(text: str) -> dict[str, Any]:
    """Parse a SavedVariables file and return ``{variable_name: value}``."""
    if len(text) > MAX_FILE_BYTES:
        raise LuaParseError("file too large")
    return _Parser(text).parse_file()


def parse_value(text: str) -> Any:
    """Parse one literal value (e.g. the table text of a packed stream chunk); nothing may follow it."""
    if len(text) > MAX_FILE_BYTES:
        raise LuaParseError("value too large")
    parser = _Parser(text)
    value = parser.value()
    parser.skip()
    if parser.i < parser.n:
        raise parser.error("unexpected text after the value")
    return value


def parse_saved_variables_bytes(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_FILE_BYTES:
        raise LuaParseError("file too large")
    return parse_saved_variables(data.decode("utf-8", errors="replace"))


class _Parser:
    def __init__(self, text: str):
        self.s = text
        self.i = 0
        self.n = len(text)
        self.depth = 0

    def error(self, message: str) -> LuaParseError:
        return LuaParseError(message, self.s, self.i)

    # -- whitespace and comments ---------------------------------------------

    def skip(self) -> None:
        s = self.s
        if self.i < self.n and s[self.i] not in _SKIP_START:
            return   # the common case: a value or separator follows right away
        while True:
            self.i = _SPACE.match(s, self.i).end()
            if not s.startswith("--", self.i):
                return
            # A long comment "--[[ ... ]]" (line comments were taken by _SPACE).
            self.i += 2
            m = _LONG_BRACKET.match(s, self.i)
            close = "]" + m.group(1) + "]"
            end = s.find(close, m.end())
            if end < 0:
                raise self.error("unterminated comment")
            self.i = end + len(close)

    def expect(self, ch: str) -> None:
        self.skip()
        if not self.s.startswith(ch, self.i):
            raise self.error(f"expected '{ch}'")
        self.i += len(ch)

    # -- top level ------------------------------------------------------------

    def parse_file(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while True:
            self.skip()
            if self.i >= self.n:
                return result
            m = _IDENT.match(self.s, self.i)
            if not m:
                raise self.error("expected variable name")
            self.i = m.end()
            self.expect("=")
            result[m.group(0)] = self.value()

    # -- values ---------------------------------------------------------------

    def value(self) -> Any:
        self.skip()
        if self.i >= self.n:
            raise self.error("unexpected end of file")
        c = self.s[self.i]
        if c == "{":
            return self.table()
        if c in "\"'":
            return self.string(c)
        if c == "[" and _LONG_BRACKET.match(self.s, self.i):
            return self.long_string()
        m = _NUMBER.match(self.s, self.i)
        if m and (c.isdigit() or c in "-." or m.group(0).lstrip("-") in ("inf", "nan")):
            self.i = m.end()
            return self.number(m.group(0))
        m = _IDENT.match(self.s, self.i)
        if m:
            word = m.group(0)
            if word in _KEYWORDS:
                self.i = m.end()
                return _KEYWORDS[word]
            raise self.error(f"unexpected identifier '{word}' (only literal data is allowed)")
        raise self.error(f"unexpected character {c!r}")

    def number(self, token: str) -> int | float:
        neg = token.startswith("-")
        body = token[1:] if neg else token
        if body in ("inf", "nan"):
            v: int | float = float(body)
        elif body[:2].lower() == "0x":
            v = int(body, 16)
        elif body.isdigit():
            v = int(body)
        else:
            v = float(body)
        return -v if neg else v

    def string(self, quote: str) -> str:
        s, n = self.s, self.n
        run = _STRING_RUN[quote]
        start = self.i + 1
        end = run.match(s, start).end()
        if end < n and s[end] == quote:   # no escapes: the text as it is
            self.i = end + 1
            return s[start:end]
        simple_end = _SIMPLE_BODY[quote].match(s, start).end()
        if simple_end < n and s[simple_end] == quote:   # only escapes like \n or \"
            self.i = simple_end + 1
            return _unescape_simple(s[start:simple_end])
        # Other escapes give raw bytes (e.g. "\195\164" is "ä"), so the string is built as UTF-8 and decoded at the end.
        out = bytearray(s[start:end].encode("utf-8"))
        self.i = end
        while True:
            if self.i >= n:
                raise self.error("unterminated string")
            c = s[self.i]
            if c == quote:
                self.i += 1
                return out.decode("utf-8", errors="replace")
            if c == "\n":
                raise self.error("newline in string")
            if c != "\\":
                end = run.match(s, self.i).end()
                out += s[self.i:end].encode("utf-8")
                self.i = end
                continue
            self.i += 1
            if self.i >= n:
                raise self.error("unterminated string")
            e = s[self.i]
            if e in _ESCAPES:
                out.append(_ESCAPES[e])
                self.i += 1
            elif e.isdigit():
                m = re.match(r"\d{1,3}", s[self.i:self.i + 3])
                code = int(m.group(0))
                if code > 255:
                    raise self.error("invalid escape")
                out.append(code)
                self.i += len(m.group(0))
            elif e == "x":
                h = s[self.i + 1:self.i + 3]
                if not re.fullmatch(r"[0-9a-fA-F]{2}", h):
                    raise self.error("invalid hex escape")
                out.append(int(h, 16))
                self.i += 3
            elif e == "z":
                self.i += 1
                while self.i < n and s[self.i] in " \t\r\n":
                    self.i += 1
            elif e == "\r":
                out.append(10)
                self.i += 2 if s.startswith("\r\n", self.i) else 1
            else:
                raise self.error(f"invalid escape '\\{e}'")

    def long_string(self) -> str:
        m = _LONG_BRACKET.match(self.s, self.i)
        close = "]" + m.group(1) + "]"
        start = m.end()
        if self.s.startswith("\n", start):
            start += 1
        end = self.s.find(close, start)
        if end < 0:
            raise self.error("unterminated long string")
        self.i = end + len(close)
        return self.s[start:end]

    def table(self) -> list[Any] | dict[Any, Any]:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise self.error("tables nested too deeply")
        self.i += 1  # {
        s = self.s
        array: list[Any] = []                # values without keys, as long as no key was given
        items: dict[Any, Any] | None = None  # once a key was given: all entries by key
        next_index = 1
        while True:
            self.skip()
            if self.i >= self.n:
                raise self.error("unterminated table")
            c = s[self.i]
            if c == "}":
                self.i += 1
                break
            if c == "[" and not _LONG_BRACKET.match(s, self.i):
                self.i += 1
                key = self.value()
                if key is None:
                    raise self.error("nil table key")
                if isinstance(key, (list, dict)):
                    raise self.error("table as table key")
                if isinstance(key, float) and key.is_integer():
                    key = int(key)
                self.expect("]")
                self.expect("=")
                if items is None:
                    items = dict(enumerate(array, 1))
                items[key] = self.value()
            else:
                m = _IDENT.match(s, self.i)
                after = m and self._peek_after(m.end())
                if m and after == "=" and m.group(0) not in _KEYWORDS:
                    self.i = m.end()
                    self.expect("=")
                    if items is None:
                        items = dict(enumerate(array, 1))
                    items[m.group(0)] = self.value()
                elif items is None:
                    array.append(self.value())
                    next_index += 1
                else:
                    items[next_index] = self.value()
                    next_index += 1
            self.skip()
            if self.i < self.n and s[self.i] in ",;":
                self.i += 1
            elif self.i < self.n and s[self.i] != "}":
                raise self.error("expected ',' or '}'")
        self.depth -= 1
        if items is None:
            return array if array else {}
        return _to_python(items)

    def _peek_after(self, pos: int) -> str:
        saved = self.i
        self.i = pos
        self.skip()
        ch = self.s[self.i] if self.i < self.n else ""
        is_assign = ch == "=" and not self.s.startswith("==", self.i)
        self.i = saved
        return "=" if is_assign else ch


def _unescape_simple(body: str) -> str:
    """Resolves the escapes of a body matched by _SIMPLE_BODY. Split at the "\\\\" pairs first (left to right, as
    the escapes are read), so the backslash of an escaped backslash never starts another escape."""
    parts = body.split("\\\\")
    for i, part in enumerate(parts):
        if "\\" in part:
            for escape, char in _SIMPLE_ESCAPES:
                part = part.replace(escape, char)
            parts[i] = part
    return "\\".join(parts)


def _to_python(items: dict[Any, Any]) -> list[Any] | dict[Any, Any]:
    if items and all(isinstance(k, int) for k in items) and set(items) == set(range(1, len(items) + 1)):
        return [items[k] for k in range(1, len(items) + 1)]
    return items


def as_list(value: Any) -> list[Any]:
    """A Lua array that may have been parsed as an empty dict (``{}``) or a list."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and not value:
        return []
    if isinstance(value, dict) and all(isinstance(k, int) for k in value):
        return [value[k] for k in sorted(value)]
    return []


def as_dict(value: Any) -> dict[Any, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {i + 1: v for i, v in enumerate(value)}
    return {}
