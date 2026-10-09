import pytest
from pathlib import Path
from infinite_memory.core.hub import Hub
from infinite_memory.core.store import VectorStore
from infinite_memory.parsers.tree_sitter_ast import UniversalASTParser
from infinite_memory.security.secret_masker import SecretMasker
from infinite_memory.security.git_guard import GitBranchGuard


def test_end_to_end_mesh_workflow(temp_dir):
    # 1. Setup multi-project workspace
    p1 = temp_dir / "saas_project"
    p2 = temp_dir / "gateway_project"
    p1.mkdir()
    p2.mkdir()

    # Write files
    (p1 / "auth.py").write_text("class Authenticator:\n    def verify(self, token):\n        return True\n", encoding="utf-8")
    (p2 / "config.env").write_text("API_KEY=sk-live999999999999999999999999\nPORT=8000\n", encoding="utf-8")

    # 2. Register projects in Hub
    registry_file = temp_dir / "registry.json"
    hub = Hub(registry_path=registry_file)
    hub.register_project("saas", p1, "saas")
    hub.register_project("gateway", p2, "gateway")

    assert "saas" in hub.list_projects()
    assert "gateway" in hub.list_projects()

    # 3. Parse and index with UniversalASTParser
    parser = UniversalASTParser()
    store = VectorStore(db_path=temp_dir / "test_mesh_db")

    chunks1 = parser.parse_file(str(p1 / "auth.py"))
    chunks2 = parser.parse_file(str(p2 / "config.env"))

    docs = []
    for c in chunks1:
        d = c.to_dict()
        d["metadata"]["project"] = "saas"
        docs.append(d)
    for c in chunks2:
        d = c.to_dict()
        d["metadata"]["project"] = "gateway"
        docs.append(d)

    indexed = store.upsert_documents(docs)
    assert indexed >= 2

    # 4. Search and verify Zero-Trust secret masking
    results = store.search("Authenticator token verification", top_k=1)
    assert len(results) > 0

    masker = SecretMasker()
    env_content = (p2 / "config.env").read_text()
    masked_env = masker.mask(env_content)
    assert "sk-live99999999" not in masked_env
    assert "<SECRET_REF:" in masked_env

    # 5. Git Branch Guard validation
    allowed, msg = GitBranchGuard.validate_write_permission(p1, allow_main_write=False)
    # Non-git directory should be allowed with message
    assert allowed is True

    # Generate unified diff
    diff = GitBranchGuard.generate_diff(p1 / "auth.py", "old content", "new content")
    assert "--- a/auth.py" in diff
    assert "+++ b/auth.py" in diff
