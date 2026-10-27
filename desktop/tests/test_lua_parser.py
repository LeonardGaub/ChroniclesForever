import pytest

from forever_chronicle.wow.lua_parser import LuaParseError, as_list, parse_saved_variables
from conftest import PROBE_SV


def test_basic_literals():
    v = parse_saved_variables('A = { ["s"] = "x", ["n"] = -1.5, ["i"] = 42, ["t"] = true, ["f"] = false, ["z"] = nil }')
    assert v["A"] == {"s": "x", "n": -1.5, "i": 42, "t": True, "f": False, "z": None}


def test_arrays_with_client_comments():
    text = '''
    DB = {
        "a", -- [1]
        "b", -- [2]
        { ["k"] = 1 }, -- [3]
    }
    '''
    assert parse_saved_variables(text)["DB"] == ["a", "b", {"k": 1}]


def test_mixed_and_numeric_keys():
    v = parse_saved_variables('X = { [1] = "a", [2] = "b", ["n"] = 2, [10] = "c" }')["X"]
    assert v == {1: "a", 2: "b", "n": 2, 10: "c"}


def test_string_escapes_and_utf8():
    v = parse_saved_variables(r'S = "line\nnext \"q\" \\ \065\066 Übersicht"')["S"]
    assert v == 'line\nnext "q" \\ AB Übersicht'


def test_multiple_variables_and_identifier_keys():
    v = parse_saved_variables("A = 1\nB = { key = 'v', other = { 1, 2 } }")
    assert v == {"A": 1, "B": {"key": "v", "other": [1, 2]}}


def test_comments_and_long_strings():
    v = parse_saved_variables("--[[ block\ncomment ]] A = [[long\ntext]] -- tail")
    assert v["A"] == "long\ntext"


def test_hex_and_exponent_numbers():
    v = parse_saved_variables("A = { 0x1F, 1e3, -2.5e-1 }")["A"]
    assert v == [31, 1000.0, -0.25]


@pytest.mark.parametrize("code", [
    'A = os.execute("calc")',
    'A = (function() return 1 end)()',
    'A = 1 + 2',
    'A = { ["x"] = loadstring("print(1)") }',
    'os.execute("calc")',
])
def test_rejects_code(code):
    with pytest.raises(LuaParseError):
        parse_saved_variables(code)


@pytest.mark.parametrize("text", ['A = { "a", ', 'A = "unterminated', 'A = { ["k"] = }', 'A =',
                                  'A = { [{}] = 1 }', 'A = { [{1}] = 1 }'])
def test_rejects_truncated(text):
    with pytest.raises(LuaParseError):
        parse_saved_variables(text)


def test_depth_limit():
    with pytest.raises(LuaParseError):
        parse_saved_variables("A = " + "{" * 100 + "}" * 100)


def test_error_has_position():
    with pytest.raises(LuaParseError) as exc:
        parse_saved_variables("A = {\n  1,\n  bad\n}")
    assert exc.value.line == 3


def test_as_list_handles_empty_table():
    assert as_list(parse_saved_variables("A = {}")["A"]) == []


def test_real_client_file():
    """The probe's SavedVariables file was written by the real Forever client."""
    if not PROBE_SV.exists():
        pytest.skip("probe results not present")
    data = parse_saved_variables(PROBE_SV.read_text(encoding="utf-8"))
    db = data["ForeverChronicleProbeDB"]
    assert db["persist"]["loadCount"] >= 1
    assert "=== Forever Chronicle Probe report" in db["lastReport"]
    assert isinstance(db["eventLog"], list) and len(db["eventLog"]) > 10
