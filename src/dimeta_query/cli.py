import argparse
import importlib.util
import os
import sys

if importlib.util.find_spec("readline"):
    import readline  # noqa: F401  # Enables arrow keys history and better input in the REPL
from typing import Any, Dict

from .formatter import format_ascii_tree
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
  m [-v] [-n [level]] [-s] <query>
                   Evaluate a matcher query
                   (e.g., m composite_type(has_name("foo")))
                   -v, --verbose: Show more detailed tree output.
                   -n, --node-only [level]: Limit tree depth (default 0).
                   -s, --summary: Print only node names, no payloads.
  p [-v] [-n [level]] [-s] <id>
                   Print a specific metadata node by ID (e.g., p !1, p 42)
                   -v, --verbose: Show more detailed tree output.
                   -n, --node-only [level]: Limit tree depth (default 0).
                   -s, --summary: Print only node names, no payloads.
  drop [-f] !<id>  Safely drop a node and cascade if refs reach 0
                   (e.g., drop !42). Use -f or --force to force drop.
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

    flags = {"verbose": False, "depth": -1, "force": False, "summary": False}
    while rest:
        rest = rest.strip()
        sub_parts = rest.split(maxsplit=1)
        word = sub_parts[0]

        if word in ("-v", "--verbose"):
            flags["verbose"] = True
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
        elif word in ("-f", "--force"):
            flags["force"] = True
        else:
            break

        rest = sub_parts[1] if len(sub_parts) > 1 else ""

    return cmd, flags, rest.strip()

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

        elif cmd == "help":
            print_help()

        elif cmd == "m":
            if not payload:
                print("Error: Must provide a query.")
                continue

            try:
                # Compile and evaluate the matcher statement safely
                matcher = execute_safely(payload, sandbox_globals)

                if not matcher or not hasattr(matcher, 'matches'):
                    print("Error: Query did not return a valid Matcher object.")
                    continue

                # Execute the query
                results = list(evaluate_query(manager.node_map.values(), matcher))

                if not results:
                    print("0 matches found.")
                else:
                    for i, res in enumerate(results, 1):
                        print(f"\nMatch {i} at !{res.node.id}:")
                        print(format_ascii_tree(
                            res, 
                            verbose=flags["verbose"], 
                            depth=flags["depth"],
                            name_only=flags["summary"]
                        ))
                    print(f"\nTotal matches: {len(results)}")

            except (SecurityError, ValueError, NameError) as e:
                print(f"Query Error: {e}")
            except Exception as e:
                print(f"Execution Error: {e}")

        elif cmd == "p":
            if not payload:
                print("Error: Must provide a node ID to print.")
                continue

            # Normalize target
            target = payload[1:] if payload.startswith("!") else payload

            node = manager.node_map.get(target)
            if not node:
                print(f"Error: Node !{target} not found.")
            else:
                res = MatchResult(node)
                print(f"\nNode !{node.id}:")
                print(format_ascii_tree(
                    res, 
                    verbose=flags["verbose"], 
                    depth=flags["depth"],
                    name_only=flags["summary"]
                ))

        elif cmd == "drop":
            if not payload:
                print("Error: Must provide a node ID to drop.")
                continue

            target = payload[1:] if payload.startswith("!") else payload

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

        elif cmd == "unparse":
            if not payload:
                print("Error: Must provide a filename to unparse to.")
                continue

            try:
                manager.save_file(payload)
                print(f"Success: Graph safely written to {payload}")
            except DanglingReferenceError as e:
                print(f"Unparse Error: {e}")
            except Exception as e:
                print(f"Failed to write file: {e}")

        else:
            print("Unknown command. Type 'help' for options.")

if __name__ == "__main__":
    main()
