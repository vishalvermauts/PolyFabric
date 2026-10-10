"""
Unit and behavior tests for System 2 Bounded Investigation layer.
Validates:
- Structured relationship classification (STATICALLY_RESOLVED, SUPPORTED, HYPOTHESISED)
- Grounded citation enforcement (no invented IDs)
- Budget limits and circuit breaker termination
- Degraded mode behavior when model fails
"""

import json
import pytest
from unittest.mock import MagicMock

from infinite_memory.core.system1 import System1Retriever, System1Config, Evidence
from infinite_memory.core.system2 import (
    System2Investigator,
    InvestigationBudget,
    RelationshipType,
    DeterministicMockModelProvider,
)


def make_mock_system1(evidence_list=None):
    s1 = MagicMock(spec=System1Retriever)
    evs = evidence_list or [
        Evidence(
            repo="flask",
            revision="rev1",
            file_path="flask/src/flask/app.py",
            start_line=10,
            end_line=25,
            symbol_name="Flask",
            chunk_type="class",
            text="class Flask: pass",
            score=0.9,
            route="hybrid",
        ),
        Evidence(
            repo="typescript",
            revision="rev2",
            file_path="typescript/src/client.ts",
            start_line=5,
            end_line=20,
            symbol_name="Client",
            chunk_type="class",
            text="class Client: pass",
            score=0.85,
            route="hybrid",
        )
    ]
    res = MagicMock()
    res.evidence = evs
    s1.search.return_value = res
    return s1


def test_system2_investigation_success():
    s1 = make_mock_system1()
    plan = {
        "sub_queries": [],
        "analysis": "Identified client and server connection.",
        "relationships": [
            {
                "source_idx": 0,
                "target_idx": 1,
                "type": "SUPPORTED_BY_CODE",
                "supporting_span": "class Flask: pass",
                "description": "Flask server exposes endpoints consumed by client.",
                "confidence": 0.85
            }
        ],
        "missing_evidence": []
    }
    provider = DeterministicMockModelProvider(responses={"trace authentication": json.dumps(plan)}, enabled_for_test=True)
    investigator = System2Investigator(system1=s1, model_provider=provider)

    result = investigator.investigate("Trace authentication flow across client and server")
    assert result.status in ("COMPLETED", "PARTIAL", "BUDGET_EXHAUSTED")
    assert len(result.evidence_gathered) >= 2
    assert len(result.relationships) > 0
    assert result.relationships[0].relationship_type == RelationshipType.SUPPORTED_BY_CODE
    assert "flask" in result.relationships[0].source_evidence_id


def test_system2_unrelated_arithmetic_negative_control():
    """Negative control: auth claims on unrelated arithmetic code must be rejected."""
    arithmetic_ev = [
        Evidence(
            repo="calc", revision="r1", file_path="calc/math.py",
            start_line=1, end_line=10, symbol_name="add", chunk_type="func",
            text="def add(a, b): return a + b\ndef sub(a, b): return a - b",
            score=0.9, route="exact_symbol"
        )
    ]
    s1 = make_mock_system1(evidence_list=arithmetic_ev)
    fake_auth_plan = {
        "sub_queries": [],
        "analysis": "Arithmetic functions found.",
        "relationships": [
            {
                "source_idx": 0,
                "target_idx": 0,
                "type": "SUPPORTED_BY_CODE",
                "supporting_span": "Bearer token header",
                "description": "Client sends Bearer token authorization header.",
                "confidence": 0.9
            }
        ],
        "missing_evidence": []
    }
    provider = DeterministicMockModelProvider(responses={"authentication": json.dumps(fake_auth_plan)}, enabled_for_test=True)
    investigator = System2Investigator(system1=s1, model_provider=provider)
    result = investigator.investigate("Trace authentication across services")
    
    # Must reject the unsupported Bearer token relationship
    assert len(result.relationships) > 0
    rel = result.relationships[0]
    assert rel.relationship_type == RelationshipType.UNRESOLVED
    assert "Rejected" in rel.description


def test_system2_invalid_or_negative_index_rejection():
    """Validates that negative or out-of-range evidence references are cleanly rejected."""
    s1 = make_mock_system1()
    invalid_plan = {
        "sub_queries": [],
        "analysis": "Testing index bounds.",
        "relationships": [
            {
                "source_idx": -1,
                "target_idx": 999,
                "type": "SUPPORTED_BY_CODE",
                "supporting_span": "test",
                "description": "Invalid index relationship",
                "confidence": 0.5
            }
        ],
        "missing_evidence": []
    }
    provider = DeterministicMockModelProvider(responses={"test": json.dumps(invalid_plan)}, enabled_for_test=True)
    investigator = System2Investigator(system1=s1, model_provider=provider)
    result = investigator.investigate("test invalid index handling")
    assert result.relationships[0].relationship_type == RelationshipType.UNRESOLVED
    assert "invalid source index" in result.relationships[0].description.lower()


def test_system2_budget_exhaustion():
    s1 = make_mock_system1()
    budget = InvestigationBudget(max_steps=1, max_retrieval_calls=1)
    provider = DeterministicMockModelProvider(enabled_for_test=True)
    investigator = System2Investigator(system1=s1, model_provider=provider, budget=budget)

    result = investigator.investigate("Analyze deep dependency graph")
    assert result.retrieval_calls_made <= 2
    assert result.status in ("COMPLETED", "PARTIAL", "BUDGET_EXHAUSTED")


def test_system2_degraded_fallback_on_missing_provider():
    """Missing provider in production must produce explicit DEGRADED status without silent mock selection."""
    s1 = make_mock_system1()
    investigator = System2Investigator(system1=s1, model_provider=None)
    result = investigator.investigate("Trace tokens")
    assert result.status == "DEGRADED"
    assert "unavailable" in result.answer.lower()
    assert len(result.evidence_gathered) > 0


def test_system2_degraded_fallback_on_model_error():
    s1 = make_mock_system1()
    broken_provider = MagicMock()
    broken_provider.generate.side_effect = RuntimeError("Provider rate-limited")
    broken_provider.name = "broken_mock"

    investigator = System2Investigator(system1=s1, model_provider=broken_provider)
    result = investigator.investigate("Trace authorization tokens")

    assert result.status == "DEGRADED"
    assert "incomplete" in result.answer.lower()
    assert len(result.evidence_gathered) > 0
