# Contributing to Infinite Memory Protocol (IMP)

Thank you for your interest in contributing to the **Infinite Memory Protocol (IMP)**! We welcome contributions from developers, researchers, and AI systems engineers worldwide.

---

## Code of Conduct

We are committed to providing a welcoming and inclusive community. Please be polite, respectful, and constructive in all issues and pull requests.

---

## Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/structzero/infinite-memory-protocol.git
   cd infinite-memory-protocol
   ```

2. **Create and activate a virtual environment (Python 3.10+):**
   ```bash
   python -m venv venv
   # On Linux/macOS:
   source venv/bin/activate
   # On Windows:
   .\venv\Scripts\Activate.ps1
   ```

3. **Install in editable mode with development dependencies:**
   ```bash
   pip install -e ".[dev]"
   ```

4. **Run the test suite:**
   ```bash
   pytest tests/
   ```

---

## Architectural Guidelines

- **Universal Multi-Language Support:** All parser changes must support Python, TypeScript, JavaScript, Go, Rust, and config/markdown files.
- **Sub-30ms P50 Latency:** Never introduce remote network calls (e.g. cloud embeddings or cloud vector databases) on the hot retrieval path. All vectors and LanceDB indexing must remain in-process.
- **Zero-Trust Security:** Any tool outputs must pass through `SecretMasker` to prevent leaking API keys or credentials into agent context windows.
- **Branch Protection:** All cross-project file writes must respect `GitBranchGuard` rules.

---

## Submitting a Pull Request

1. Fork the repository and create your branch from `main`:
   ```bash
   git checkout -b feature/my-enhancement
   ```
2. Ensure all unit and integration tests pass:
   ```bash
   pytest tests/
   ```
3. Format and lint your code using `black` and `ruff`:
   ```bash
   ruff check src/ tests/
   ```
4. Commit your changes and open a Pull Request with a clear description and benchmark impact.
