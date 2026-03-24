import pytest

from dimeta_query.parser import MetadataParseError, parse_metadata


def test_lexer_handles_malformed_input():
    with pytest.raises(MetadataParseError):
        parse_metadata('!0 = !{!"test"')

def test_missing_equals():
    with pytest.raises(MetadataParseError):
        parse_metadata('!0 !{!"test"}')

def test_invalid_operand():
    with pytest.raises(MetadataParseError):
        parse_metadata('!0 = !{i32 !}') # lone ! is invalid operand

def test_invalid_start():
    with pytest.raises(MetadataParseError):
        parse_metadata('0 = !{!"test"}') # missing ! at start
