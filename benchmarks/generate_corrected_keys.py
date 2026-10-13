import os
import json
import urllib.request
import urllib.error
from pathlib import Path

RUN_ID = "RUN_20261013_FARMWATCH_3KEY_CORRECTED"
GATEWAY_URL = os.environ.get("LITELLM_BASE_URL", "https://router.helixengine.app")
VAULT_PATH = Path("/tmp/.eval_keys_vault.json")

if not VAULT_PATH.exists():
    raise RuntimeError(f"Vault not found at {VAULT_PATH}")

with open(VAULT_PATH, "r") as f:
    vault = json.load(f)

master_key = vault["master_key"]
if not master_key:
    raise RuntimeError("Master key missing from vault")

approaches = [
    ("PolyFabricRetrieval", "polyfabric_retrieval"),
    ("TargetedSearch", "targeted_search"),
    ("WholeFileContext", "whole_file_context"),
]

new_keys = {}

print(f"Creating 3 fresh virtual keys for run: {RUN_ID} on {GATEWAY_URL}")
for suffix, approach_name in approaches:
    alias = f"{RUN_ID}-{suffix}"
    payload = {
        "key_alias": alias,
        "models": ["gemini-2.5-flash"],
        "metadata": {
            "run_id": RUN_ID,
            "approach": approach_name,
            "experiment": "PolyFabric vs Baselines 3-Key Evaluation"
        },
        "max_budget": 15.0
    }
    
    req = urllib.request.Request(
        f"{GATEWAY_URL}/key/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {master_key}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            generated_key = data["key"]
            new_keys[alias] = generated_key
            print(f"  ✓ Created key for alias: {alias} (expires={data.get('expires', 'never')})")
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        print(f"  ✗ Failed to create key for {alias}: HTTP {e.code} - {err_msg}")
        raise

# Update vault
vault["keys"].update(new_keys)
with open(VAULT_PATH, "w") as f:
    json.dump(vault, f, indent=2)

print("\nVault successfully updated with 3 fresh keys!")
print("Aliases configured:")
for a in new_keys:
    print(f"  - {a}")
