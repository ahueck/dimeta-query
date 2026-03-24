# dimeta-query

*dimeta-query* is a Python-based tool for parsing and querying LLVM metadata based on `*.ll` (text) files.
It provides a CLI and a programmatic interface for exploring and manipulating the metadata graph.

*Disclaimer*: This tool has been created with support of an agentic AI tool.

## Usage

Run the CLI on an LLVM IR file to open the interactive query engine:

```bash
$ dimeta-query --help
usage: dimeta-query [-h] file

dimeta-query: Interactive LLVM Metadata Query Engine

positional arguments:
  file        Path to the .ll file to analyze

options:
  -h, --help  show this help message and exit
```

Example interactive session:

```bash
$ dimeta-query example-inputs/test.ll
Parsing 'example-inputs/test.ll'...
Loaded 37 nodes from 23 metadata definitions.
Warning: 14 proxy nodes were referenced but never defined.
Type 'help' for available commands.
dimeta> help

Available Commands:
  m [-v] <query>   Evaluate a matcher query (e.g., m composite_type(has_name("foo")))
                   Use -v or --verbose for more detailed tree output (shows property names).
  drop [-f] !<id>  Safely drop a node and cascade if refs reach 0 (e.g., drop !42)
                   Use -f or --force to force drop even if referenced.
  unparse <file>   Write the current metadata graph to a file
  help             Show this help message
  exit / quit      Exit the REPL
```

## Installation

### Via pip

Install directly from the source:

```bash
pip install .
```

For development, install with the `dev` and `test` extras:

```bash
pip install -e ".[dev,test]"
```

### Standalone Executable

Build a self-contained `.pyz` executable using `shiv` in folder `dist/`.

```bash
$ make build
 > rm -rf build dist
 > mkdir -p dist
 > shiv --compressed -o dist/dimeta-query.pyz -e dimeta_query.cli:main .
```

## Development

The project tools are governed by the `Makefile` and `pyproject.toml`.

### Running Tests

We use `pytest` for testing.

```bash
$ pytest --tb=short
============================= test session starts ==============================
...
tests/test_cli.py .............                                          [ 13%]
...
tests/test_unparser.py .                                                 [100%]

======================== 94 passed, 1 skipped in 8.20s =========================
```

### Linting and Type Checking 

Code style and linting are enforced by `ruff`.
Static type checking is provided by `mypy`.

```bash
$ ruff check .
$ mypy src
```

## Project Structure

```text
src/dimeta_query/
├── __init__.py
├── __main__.py
├── cli.py            # CLI entry point and argument parsing
├── formatter.py      # Output formatting and tree visualization
├── grammar.lark      # Lark grammar rules for LLVM metadata syntax
├── graph_manager.py  # Graph mutation, reference tracking, and garbage collection
├── ir.py             # Raw LLVM IR text processing and reference extraction
├── matchers.py       # Specific query matchers for node types and properties
├── model.py          # Core data models (MDNode, MDSpecializedNode, etc.)
├── modifiers.py      # String modifiers for queries (e.g., fuzzy, demangle)
├── parser.py         # Lark-based parser for building the metadata graph
├── query.py          # Query execution engine and base matching logic
├── repl.py           # Interactive query and manipulation shell
└── unparser.py       # Graph state validation and structural checks
tests/                # Test suite
```