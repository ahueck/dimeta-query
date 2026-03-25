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
  m [-v] [-n] <query>
                   Evaluate a matcher query
                   (e.g., m composite_type(has_name("foo")))
                   -v, --verbose: Show more detailed tree output.
                   -n, --node-only: Print only the matching node, no children.
  p [-v] [-n] <id> Print a specific metadata node by ID (e.g., p !1, p 42)
                   -v, --verbose: Show more detailed tree output.
                   -n, --node-only: Print only the node, no children.
  drop [-f] !<id>  Safely drop a node and cascade if refs reach 0
                   (e.g., drop !42). Use -f or --force to force drop.
  unparse <file>   Write the current metadata graph to a file
  help             Show this help message
  exit / quit      Exit the REPL
""".strip() + "\n")

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
        except EOFError:
            print("\nExiting.")
            break
        except KeyboardInterrupt:
            print("\nExiting.")
            break
            
        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            break
            
        elif user_input.lower() == "help":
            print_help()
            
        elif user_input.startswith("m "):
            query_str = user_input[2:].strip()
            verbose = False
            shallow = False
            
            # Simple flag parsing loop
            while True:
                if query_str.startswith("-v "):
                    verbose = True
                    query_str = query_str[3:].strip()
                elif query_str.startswith("--verbose "):
                    verbose = True
                    query_str = query_str[10:].strip()
                elif query_str == "-v" or query_str == "--verbose":
                    verbose = True
                    query_str = ""
                    break
                elif query_str.startswith("-n "):
                    shallow = True
                    query_str = query_str[3:].strip()
                elif query_str.startswith("--node-only "):
                    shallow = True
                    query_str = query_str[12:].strip()
                elif query_str == "-n" or query_str == "--node-only":
                    shallow = True
                    query_str = ""
                    break
                else:
                    break

            try:
                # Compile and evaluate the matcher statement safely
                matcher = execute_safely(query_str, sandbox_globals)
                
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
                        print(format_ascii_tree(res, verbose=verbose, shallow=shallow))
                    print(f"\nTotal matches: {len(results)}")

            except (SecurityError, ValueError, NameError) as e:
                print(f"Query Error: {e}")
            except Exception as e:
                print(f"Execution Error: {e}")

        elif user_input.startswith("p "):
            parts = user_input[2:].strip().split()
            verbose = False
            shallow = False
            target = ""
            
            i = 0
            while i < len(parts):
                arg = parts[i]
                if arg in ("-v", "--verbose"):
                    verbose = True
                elif arg in ("-n", "--node-only"):
                    shallow = True
                else:
                    target = arg
                i += 1
            
            if not target:
                print("Error: Must provide a node ID to print.")
                continue

            # Normalize target
            if target.startswith("!"):
                target = target[1:]
            
            node = manager.node_map.get(target)
            if not node:
                print(f"Error: Node !{target} not found.")
            else:
                res = MatchResult(node)
                print(f"\nNode !{node.id}:")
                print(format_ascii_tree(res, verbose=verbose, shallow=shallow))

        elif user_input.startswith("drop "):
            parts = user_input[5:].split()
            force = False
            target = ""
            for p in parts:
                if p in ("--force", "-f"):
                    force = True
                else:
                    target = p
            
            if not target:
                print("Error: Must provide a node ID to drop.")
                continue

            if target.startswith("!"):
                target = target[1:]
            
            try:
                drop_node(target, manager.node_map, force=force)
                print(
                    f"Success: Dropped !{target} (force={force}) and executed cascade."
                )
            except ValueError as e:
                print(f"Failed to drop !{target}: {e}")
            except Exception as e:
                print(f"Error dropping node: {e}")

        elif user_input.startswith("unparse "):
            filename = user_input[8:].strip()
            if not filename:
                print("Error: Must provide a filename to unparse to.")
                continue
                
            try:
                manager.save_file(filename)
                print(f"Success: Graph safely written to {filename}")
            except DanglingReferenceError as e:
                print(f"Unparse Error: {e}")
            except Exception as e:
                print(f"Failed to write file: {e}")
        
        else:
            print("Unknown command. Type 'help' for options.")

if __name__ == "__main__":
    main()
