import time
import re
from typing import Dict, Any, Optional, List
from .hub import Hub


class SystemOneRouter:
    """System 1 fast heuristic & hot-cache intent router (<2ms).
    
    Prevents burning LLM inference tokens on deterministic decisions.
    Classifies prompt intents:
      - pinpoint_symbol (exact AST lookup)
      - pinpoint_ui (UI/styling/logo lookup)
      - gateway_provision (keys, auth, credentials)
      - mesh_cross_read (multi-repo cross-referencing)
      - vector_search (semantic codebase retrieval)
    """

    def __init__(self, hub: Optional[Hub] = None):
        self.hub = hub or Hub()

    def route(self, prompt: str) -> Dict[str, Any]:
        t0 = time.perf_counter()
        p = prompt.strip()
        p_lower = p.lower()

        # 1. UI hot-cache pattern
        ui_keywords = ["logo", "color", "theme", "header", "navbar", "styling", "css", "tailwind", "ui component"]
        if any(kw in p_lower for kw in ui_keywords):
            matched_kw = next((kw for kw in ui_keywords if kw in p_lower), "ui")
            target_proj = self._infer_project(p_lower)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "intent": "pinpoint_ui",
                "target_project": target_proj,
                "target_entity": matched_kw,
                "confidence": 0.98,
                "latency_ms": round(latency_ms, 3),
            }

        # 2. Cross-repo multi-hop mesh pattern
        if ("across" in p_lower or "cross" in p_lower or "both" in p_lower or "integrate" in p_lower) and len(self.hub.list_projects()) > 1:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "intent": "mesh_cross_read",
                "target_project": "mesh_all",
                "target_entity": "cross_reference",
                "confidence": 0.95,
                "latency_ms": round(latency_ms, 3),
            }

        # 3. Security / gateway / credentials pattern
        gw_keywords = ["api key", "apikey", "secret", "token", "gateway", "credential", "auth header", "master_key"]
        if any(kw in p_lower for kw in gw_keywords):
            target_proj = self._infer_project(p_lower)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "intent": "gateway_provision",
                "target_project": target_proj,
                "target_entity": "credentials",
                "confidence": 0.97,
                "latency_ms": round(latency_ms, 3),
            }

        # 4. Symbol pinpointing (classes, functions, filenames)
        symbol_match = re.search(r'\b(class|def|fn|function|interface|const)\s+([A-Za-z0-9_]+)', prompt)
        if symbol_match:
            entity = symbol_match.group(2)
            target_proj = self._infer_project(p_lower)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "intent": "pinpoint_symbol",
                "target_project": target_proj,
                "target_entity": entity,
                "confidence": 0.99,
                "latency_ms": round(latency_ms, 3),
            }

        # 5. Default: semantic vector search
        target_proj = self._infer_project(p_lower)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "intent": "vector_search",
            "target_project": target_proj,
            "target_entity": None,
            "confidence": 0.90,
            "latency_ms": round(latency_ms, 3),
        }

    def _infer_project(self, prompt_lower: str) -> str:
        projects = self.hub.list_projects()
        for name in projects.keys():
            if name.lower() in prompt_lower:
                return name
        return "general"


def system_one_router(prompt: str) -> Dict[str, Any]:
    """Functional wrapper for SystemOneRouter."""
    return SystemOneRouter().route(prompt)
