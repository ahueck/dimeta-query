import glob
from importlib import resources

import pytest
from lark import Lark

from dimeta_query.parser import parse_metadata


@pytest.fixture(scope="session")
def parser():
    grammar_text = resources.files("dimeta_query").joinpath("grammar.lark").read_text()
    return Lark(grammar_text, start='metadata_def', parser='lalr')

def extract_metadata_lines(filepath):
    lines = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('!') and '=' in line:
                lines.append(line)
    return lines

@pytest.mark.parametrize("filepath", glob.glob('example-inputs/*.ll'))
def test_example_inputs(parser, filepath):
    lines = extract_metadata_lines(filepath)
    for line in lines:
        try:
            parse_metadata(line)
        except Exception as e:
            pytest.fail(f"Failed to parse line '{line}' in file {filepath}: {e}")

# Optional test for custom inputs in 'test-input' directory
custom_inputs = glob.glob('test-input/*.ll')
if not custom_inputs:
    # If no files found, add a dummy skipped parameter to avoid collection errors
    custom_inputs = [
        pytest.param(
            "dummy",
            marks=pytest.mark.skip(reason="No .ll files found in test-input directory"),
        )
    ]

@pytest.mark.parametrize("filepath", custom_inputs)
def test_custom_inputs(parser, filepath):
    if filepath == "dummy":
        return
        
    lines = extract_metadata_lines(filepath)
    for line in lines:
        try:
            parse_metadata(line)
        except Exception as e:
            pytest.fail(f"Failed to parse line '{line}' in file {filepath}: {e}")
