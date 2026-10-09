#!/usr/bin/env bash
set -e

echo "=== Installing Infinite Memory Protocol (IMP) ==="

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is required but not installed. Aborting."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Detected Python version: $PYTHON_VERSION"

# Upgrade pip & install
python3 -m pip install --upgrade pip
python3 -m pip install -e .

echo "=== Infinite Memory Protocol successfully installed! ==="
echo "Try running: memory-mesh --help"
