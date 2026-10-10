FROM python:3.11-slim

WORKDIR /app

# System deps for tree-sitter native builds
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git curl && \
    rm -rf /var/lib/apt/lists/*

# Copy project and install
COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

# Default: run the full test suite
CMD ["python", "-m", "pytest", "tests/", "-v", "--tb=short"]
