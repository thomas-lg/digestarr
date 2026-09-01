#!/bin/sh
# Clean up generated files and caches

set -e

cd "$(dirname "$0")/.."

echo "🧹 Cleaning up Digestarr..."
echo ""

# Ask for confirmation
printf "This will remove test coverage and caches. Continue? (y/n) "
read -r reply
case "$reply" in
    [Yy]) ;;
    *)
        echo ""
        echo "Cancelled."
        exit 0
        ;;
esac
echo ""

# Clean Python caches
echo "Removing Python caches..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true

# Clean coverage reports
if [ -d "htmlcov" ]; then
    echo "Removing coverage reports..."
    rm -rf htmlcov/
fi
if [ -f ".coverage" ]; then
    rm -f .coverage
fi
if [ -f "coverage.xml" ]; then
    rm -f coverage.xml
fi

echo ""
echo "✨ Clean complete!"
