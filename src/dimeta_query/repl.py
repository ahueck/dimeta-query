import ast
from typing import Any, Dict


class SecurityError(Exception):
    """Raised when an unauthorized AST node is encountered in the REPL sandbox."""
    pass

class SandboxVisitor(ast.NodeVisitor):
    ALLOWED_NODES = {
        ast.Call,
        ast.Name,
        ast.Constant,
        ast.keyword,
        ast.Load,
        ast.Store,
        ast.Assign,
        ast.Expr,
        ast.Module,
    }

    def generic_visit(self, node: ast.AST) -> Any:
        if type(node) not in self.ALLOWED_NODES:
            raise SecurityError(f"Unauthorized AST node: {type(node).__name__}")
        return super().generic_visit(node)

def execute_safely(user_input: str, globals_dict: Dict[str, Any]) -> Any:
    source = f"_query = {user_input}"
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ValueError(f"Syntax error in query: {e}") from e
    
    visitor = SandboxVisitor()
    visitor.visit(tree)
    compiled_code = compile(tree, filename="<ast>", mode="exec")
    
    safe_globals: Dict[str, Any] = {
        "__builtins__": {},
    }
    safe_globals.update(globals_dict)
    safe_locals: Dict[str, Any] = {}
    exec(compiled_code, safe_globals, safe_locals)

    return safe_locals.get("_query")
