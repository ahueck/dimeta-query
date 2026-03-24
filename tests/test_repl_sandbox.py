import pytest

from dimeta_query.repl import SecurityError, execute_safely


def test_repl_sandbox_allows_whitelisted_calls():
    def mock_matcher(arg):
        return f"matched_{arg}"

    globals_dict = {
        "composite_type": mock_matcher,
        "has_identifier": mock_matcher,
        "demangle": mock_matcher,
    }
    
    user_input = 'composite_type(has_identifier(demangle("foo")))'
    
    result = execute_safely(user_input, globals_dict)
    
    assert result == "matched_matched_matched_foo"

def test_repl_sandbox_rejects_unauthorized_ast_nodes():
    globals_dict = {}

    malicious_inputs_ast = [
        "__import__('os').system('ls')",
        "[x for x in range(10)]",
        "lambda x: x",
        "1 + 1",
        "open('/etc/passwd').read()",
    ]

    for user_input in malicious_inputs_ast:
        with pytest.raises(SecurityError) as exc:
            execute_safely(user_input, globals_dict)
        assert "Unauthorized AST node" in str(exc.value)

def test_repl_sandbox_builtins_wiped():
    globals_dict = {}
    malicious_inputs_builtins = [
        "eval('1+1')"
    ]
    for user_input in malicious_inputs_builtins:
        with pytest.raises(NameError):
            execute_safely(user_input, globals_dict)

def test_repl_sandbox_catches_syntax_error():
    with pytest.raises(ValueError) as exc:
        execute_safely("composite_type(", {})
    assert "Syntax error" in str(exc.value)
