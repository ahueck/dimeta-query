
def test_environment_sanity():
    # Verify we can import lark from dependency/lark or installed
    import lark
    print(f"Lark path: {lark.__file__}")
    assert lark is not None

def test_project_structure():
    import dimeta_query
    assert dimeta_query is not None
