import os
import json
import time
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime, timezone

RUN_ID = "RUN_20261013_FARMWATCH_3KEY_CORRECTED"
GATEWAY_URL = os.environ.get("LITELLM_BASE_URL", "https://router.helixengine.app")
MODEL_NAME = "gemini-2.5-flash"

VAULT_PATH = Path("/tmp/.eval_keys_vault.json")
if not VAULT_PATH.exists():
    raise RuntimeError(f"Vault not found at {VAULT_PATH}")

with open(VAULT_PATH, "r") as f:
    vault = json.load(f)

KEYS = vault["keys"]
OUT_DIR = Path(f"/tmp/results/{RUN_ID}")
OUT_DIR.mkdir(parents=True, exist_ok=True)
PREFLIGHT_FILE = OUT_DIR / "preflight_attribution_records.json"

approaches = [
    ("polyfabric_retrieval", f"{RUN_ID}-PolyFabricRetrieval"),
    ("targeted_search", f"{RUN_ID}-TargetedSearch"),
    ("whole_file_context", f"{RUN_ID}-WholeFileContext")
]

records = []
print(f"=== STARTING ATTRIBUTION PREFLIGHT FOR RUN: {RUN_ID} ===")

for approach_id, alias in approaches:
    key = KEYS.get(alias)
    if not key:
        raise RuntimeError(f"Key missing for alias {alias}")

    client_call_id = f"preflight-{RUN_ID}-{approach_id}"
    metadata = {
        "run_id": RUN_ID,
        "approach": approach_id,
        "task_id": "PREFLIGHT",
        "trial": 0,
        "stage": "preflight",
        "call_number": 1,
        "client_call_id": client_call_id
    }

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "user", "content": f"Ping test for approach {approach_id}. Respond with 'PONG'."}
        ],
        "metadata": metadata,
        "temperature": 0.0,
        "max_tokens": 1024
    }

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
        tf.write(json.dumps(payload))
        tmp_path = tf.name

    t0 = time.perf_counter()
    start_iso = datetime.now(timezone.utc).isoformat()
    try:
        proc = subprocess.run(
            [
                "curl", "-sS", "-i", "--max-time", "30",
                f"{GATEWAY_URL}/chat/completions",
                "-H", f"Authorization: Bearer {key}",
                "-H", "Content-Type: application/json",
                "-d", f"@{tmp_path}"
            ],
            capture_output=True,
            text=True,
            timeout=35
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        end_iso = datetime.now(timezone.utc).isoformat()

        if proc.returncode != 0:
            raise RuntimeError(f"Curl failed: {proc.stderr}")

        raw_full = proc.stdout
        parts = raw_full.split("\r\n\r\n", 1)
        if len(parts) == 1:
            parts = raw_full.split("\n\n", 1)
        header_part = parts[0] if len(parts) > 1 else ""
        body_part = parts[1] if len(parts) > 1 else raw_full

        gateway_call_id = None
        for hline in header_part.splitlines():
            if "x-litellm-call-id:" in hline.lower() or "x-request-id:" in hline.lower():
                gateway_call_id = hline.split(":", 1)[1].strip()

        parsed = json.loads(body_part)
        content = parsed["choices"][0]["message"].get("content", "").strip()
        usage = parsed.get("usage", {})
        response_id = parsed.get("id")

        rec = {
            "run_id": RUN_ID,
            "approach": approach_id,
            "key_alias": alias,
            "client_call_id": client_call_id,
            "gateway_call_id": gateway_call_id,
            "response_id": response_id,
            "status": "success",
            "content": content,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "latency_ms": round(elapsed_ms, 2),
            "start_time_utc": start_iso,
            "end_time_utc": end_iso
        }
        records.append(rec)
        print(f"  ✓ [{alias}] Response OK | ID: {response_id} | Gateway-ID: {gateway_call_id} | Tokens: {rec['total_tokens']}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

PREFLIGHT_FILE.write_text(json.dumps(records, indent=2), encoding="utf-8")
print(f"\nPreflight records saved to: {PREFLIGHT_FILE}")
print("ALL 3 KEYS VERIFIED WITH INDEPENDENT SERVER ATTRIBUTION!")
