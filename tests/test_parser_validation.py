from importlib import resources

import pytest
from lark import Lark


@pytest.fixture
def parser():
    grammar_text = resources.files("dimeta_query").joinpath("grammar.lark").read_text()
    return Lark(grammar_text, start='metadata_def', parser='lalr')

def test_simple_tuple(parser):
    tree = parser.parse('!0 = !{!"test"}')
    assert tree.data == 'normal_def'

def test_distinct_specialized(parser):
    tree = parser.parse('!0 = distinct !DICompileUnit(language: DW_LANG_Fortran95)')
    assert tree.data == 'distinct_def'

def test_named_metadata(parser):
    tree = parser.parse('!llvm.dbg.cu = !{!0}')
    assert tree.data == 'normal_def'

def test_nested_tuples(parser):
    tree = parser.parse('!0 = !{!1, !{!2, !3}}')
    assert tree.data == 'normal_def'

def test_typed_operands(parser):
    tree = parser.parse('!0 = !{i32 42, i64 100}')
    assert tree.data == 'normal_def'

def test_compound_flags(parser):
    tree = parser.parse(
        '!0 = !DISubprogram(spFlags: DISPFlagDefinition | DISPFlagOptimized)'
    )
    assert tree.data == 'normal_def'


def test_complex_expression(parser):
    tree = parser.parse(
        '!0 = !DIExpression(DW_OP_push_object_address, DW_OP_plus_uconst, '
        '32, DW_OP_deref)'
    )
    assert tree.data == 'normal_def'
