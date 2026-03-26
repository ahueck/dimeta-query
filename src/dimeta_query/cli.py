import argparse
import importlib.util
import os
import sys

if importlib.util.find_spec("readline"):
    import readline  # noqa: F401  # Enables arrow keys history and better input in the REPL
from typing import Any, Dict

from .formatter import format_ascii_tree, format_flat_list
from .graph_manager import drop_node
from .ir import IRManager

# Import all matchers and modifiers to inject into the sandbox
from .matchers import (
    basic_type,
    composite_type,
    derived_type,
    file_node,
    has_attr,
    has_base_type,
    has_child,
    has_element,
    has_flag,
    has_name,
    has_property,
    has_scope,
    has_tag,
    has_type,
    lexical_block,
    local_variable,
    node,
    subprogram,
    subrange,
)
from .modifiers import demangle, fuzzy
from .query import MatchResult, evaluate_query
from .repl import SecurityError, execute_safely
from .unparser import DanglingReferenceError


def setup_sandbox_globals() -> Dict[str, Any]:
    """Returns a dictionary of all whitelisted functions allowed in the REPL."""
    return {
        "node": node,
        "local_variable": local_variable,
        "composite_type": composite_type,
        "derived_type": derived_type,
        "basic_type": basic_type,
        "subrange": subrange,
        "subprogram": subprogram,
        "file_node": file_node,
        "lexical_block": lexical_block,
        "has_name": has_name,
        "has_flag": has_flag,
        "has_type": has_type,
        "has_scope": has_scope,
        "has_element": has_element,
        "has_child": has_child,
        "has_base_type": has_base_type,
        "has_tag": has_tag,
        "has_attr": has_attr,
        "has_property": has_property,
        "fuzzy": fuzzy,
        "demangle": demangle
    }

def print_help() -> None:
    print("""
Available Commands:
  m [-v] [-n [level]] [-s] [-l] <query>
                   Evaluate a matcher query
                   (e.g., m composite_type(has_name("foo")))
                   -v, --verbose: Show more detailed tree output.
                   -n, --node-only [level]: Limit tree depth (default 0).
                   -s, --summary: Print only node names, no payloads.
                   -l, --list: Print as a flat, deduplicated list.
  p [-v] [-n [level]] [-s] [-l] <id>
                   Print a specific metadata node by ID (e.g., p !1, p 42)
                   -v, --verbose: Show more detailed tree output.
                   -n, --node-only [level]: Limit tree depth (default 0).
                   -s, --summary: Print only node names, no payloads.
                   -l, --list: Print as a flat, deduplicated list.
  drop [-f] <id|query>
                   Safely drop a node by ID or all nodes matching a query
                   (e.g., drop !42, drop node(has_name("test")))
                   Use -f or --force to force drop.
  sweep [-a]       Remove all metadata nodes not reachable from IR
                   -a, --all: Also discard unreferenced named metadata.
  unparse <file>   Write the current metadata graph to a file
  help             Show this help message
  exit / quit      Exit the REPL
""".strip() + "\n")

def parse_repl_line(line: str) -> tuple[str, dict[str, Any], str]:
    """Parses a REPL line into (command, flags, payload)."""
    parts = line.strip().split(maxsplit=1)
    if not parts:
        return "", {}, ""

    cmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    flags = {
        "verbose": False, 
        "depth": -1, 
        "force": False, 
        "summary": False,
        "flat": False,
        "all": False
    }
    while rest:
        rest = rest.strip()
        sub_parts = rest.split(maxsplit=1)
        word = sub_parts[0]

        if word in ("-v", "--verbose"):
            flags["verbose"] = True
        elif word in ("-a", "--all"):
            flags["all"] = True
        elif word in ("-n", "--node-only"):
            flags["depth"] = 0
            if len(sub_parts) > 1:
                peek_parts = sub_parts[1].split(maxsplit=1)
                # Only consume the digit as depth if it's not the last word.
                # If it's the last word, assume it's the node ID (payload).
                if peek_parts[0].isdigit() and len(peek_parts) > 1:
                    flags["depth"] = int(peek_parts[0])
                    rest = peek_parts[1]
                    continue
        elif word in ("-s", "--summary"):
            flags["summary"] = True
        elif word in ("-l", "--list"):
            flags["flat"] = True
        elif word in ("-f", "--force"):
            flags["force"] = True
        else:
            break

        rest = sub_parts[1] if len(sub_parts) > 1 else ""

    return cmd, flags, rest.strip()

def is_matcher_expression(payload: str) -> bool:
    """Heuristic to distinguish between a node ID and a matcher expression."""
    p = payload.strip()
    if not p:
        return False
    # If it starts with ! and has no parens, it's almost certainly an ID
    if p.startswith("!") and "(" not in p:
        return False
    # If it's purely digits, it's an ID
    if p.isdigit():
        return False
    # If it has parens, we treat it as a matcher expression
    return "(" in p and ")" in p


def _normalize_node_id(payload: str) -> str:
    return payload[1:] if payload.startswith("!") else payload


def _format_result(res: MatchResult, flags: dict[str, Any]) -> str:
    if flags["flat"]:
        return format_flat_list(
            res,
            depth=flags["depth"],
            name_only=flags["summary"],
        )
    return format_ascii_tree(
        res,
        verbose=flags["verbose"],
        depth=flags["depth"],
        name_only=flags["summary"],
    )


def _compile_matcher(payload: str, sandbox_globals: dict[str, Any]) -> Any:
    matcher = execute_safely(payload, sandbox_globals)
    if not matcher or not hasattr(matcher, "matches"):
        raise ValueError("Query did not return a valid Matcher object.")
    return matcher


def _evaluate_matches(manager: IRManager, matcher: Any) -> list[MatchResult]:
    return list(evaluate_query(manager.node_map.values(), matcher))


def _handle_match_command(
    manager: IRManager,
    flags: dict[str, Any],
    payload: str,
    sandbox_globals: dict[str, Any],
) -> None:
    if not payload:
        print("Error: Must provide a query.")
        return

    try:
        matcher = _compile_matcher(payload, sandbox_globals)
        results = _evaluate_matches(manager, matcher)

        if not results:
            print("0 matches found.")
            return

        for i, res in enumerate(results, 1):
            print(f"\nMatch {i} at !{res.node.id}:")
            print(_format_result(res, flags))
        print(f"\nTotal matches: {len(results)}")
    except (SecurityError, ValueError, NameError) as e:
        print(f"Query Error: {e}")
    except Exception as e:
        print(f"Execution Error: {e}")


def _handle_print_command(
    manager: IRManager,
    flags: dict[str, Any],
    payload: str,
) -> None:
    if not payload:
        print("Error: Must provide a node ID to print.")
        return

    target = _normalize_node_id(payload)
    node = manager.node_map.get(target)
    if not node:
        print(f"Error: Node !{target} not found.")
        return

    res = MatchResult(node)
    print(f"\nNode !{node.id}:")
    print(_format_result(res, flags))


def _handle_drop_command(
    manager: IRManager,
    flags: dict[str, Any],
    payload: str,
    sandbox_globals: dict[str, Any],
) -> None:
    if not payload:
        print("Error: Must provide a node ID to drop.")
        return

    if is_matcher_expression(payload):
        try:
            matcher = _compile_matcher(payload, sandbox_globals)
            results = _evaluate_matches(manager, matcher)

            if not results:
                print("0 matches found.")
                return

            target_ids = []
            seen_ids = set()
            for res in results:
                if res.node.id not in seen_ids:
                    target_ids.append(res.node.id)
                    seen_ids.add(res.node.id)

            success_count = 0
            for target_id in target_ids:
                try:
                    if target_id not in manager.node_map:
                        continue
                    drop_node(target_id, manager.node_map, force=flags["force"])
                    success_count += 1
                except ValueError as e:
                    print(f"Failed to drop !{target_id}: {e}")

            print(
                f"Success: Dropped {success_count} matching nodes "
                f"(force={flags['force']})."
            )
        except (SecurityError, ValueError, NameError) as e:
            print(f"Query Error: {e}")
        except Exception as e:
            print(f"Execution Error: {e}")
        return

    target = _normalize_node_id(payload)
    try:
        drop_node(target, manager.node_map, force=flags["force"])
        print(
            f"Success: Dropped !{target} (force={flags['force']}) "
            "and executed cascade."
        )
    except ValueError as e:
        print(f"Failed to drop !{target}: {e}")
    except Exception as e:
        print(f"Error dropping node: {e}")


def _handle_sweep_command(manager: IRManager, flags: dict[str, Any]) -> None:
    try:
        count = manager.sweep_unreferenced_metadata(discard_named=flags["all"])
        print(f"Success: Swept {count} unreferenced metadata definitions.")
        print(f"Current count: {len(manager.node_map)} nodes.")
    except Exception as e:
        print(f"Sweep Error: {e}")


def _handle_unparse_command(manager: IRManager, payload: str) -> None:
    if not payload:
        print("Error: Must provide a filename to unparse to.")
        return

    try:
        manager.save_file(payload)
        print(f"Success: Graph safely written to {payload}")
    except DanglingReferenceError as e:
        print(f"Unparse Error: {e}")
    except Exception as e:
        print(f"Failed to write file: {e}")

def main() -> None:

    parser = argparse.ArgumentParser(
        description="dimeta-query: Interactive LLVM Metadata Query Engine"
    )
    parser.add_argument("file", help="Path to the .ll file to analyze")
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"Error: File '{args.file}' not found.")
        sys.exit(1)

    print(f"Parsing '{args.file}'...")
    manager = IRManager()

    try:
        manager.parse_file(args.file)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(
        f"Loaded {len(manager.node_map)} nodes from "
        f"{manager.metadata_count} metadata definitions."
    )
    
    if manager.unresolved:
        print(
            f"Warning: {len(manager.unresolved)} proxy nodes were "
            f"referenced but never defined."
        )

    sandbox_globals = setup_sandbox_globals()

    print("Type 'help' for available commands.")
    
    while True:
        try:
            user_input = input("dimeta> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not user_input:
            continue

        cmd, flags, payload = parse_repl_line(user_input)

        if cmd in ("exit", "quit"):
            break

        if cmd == "help":
            print_help()
            continue

        if cmd == "m":
            _handle_match_command(manager, flags, payload, sandbox_globals)
        elif cmd == "p":
            _handle_print_command(manager, flags, payload)
        elif cmd == "drop":
            _handle_drop_command(manager, flags, payload, sandbox_globals)
        elif cmd == "sweep":
            _handle_sweep_command(manager, flags)
        elif cmd == "unparse":
            _handle_unparse_command(manager, payload)
        else:
            print("Unknown command. Type 'help' for options.")
            continue

if __name__ == "__main__":
    main()
