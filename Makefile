BUILD_DIR = build
DIST_DIR = dist
APP_NAME = dimeta-query.pyz

.PHONY: all clean build lint test typecheck

all: lint typecheck test build

clean:
	rm -rf $(BUILD_DIR) $(DIST_DIR)

lint:
	ruff check .

test:
	pytest

typecheck:
	mypy src

build: clean
	mkdir -p $(DIST_DIR)
	shiv --compressed -o $(DIST_DIR)/$(APP_NAME) -e dimeta_query.cli:main ".[tui]"

run: build
	./$(DIST_DIR)/$(APP_NAME) --help
