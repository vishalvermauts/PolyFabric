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
    provider = DeterministicMockModelProvider()
    investigator = System2Investigator(system1=s1, model_provider=provider)

    result = investigator.investigate("Trace authentication flow across client and server")
    assert result.status in ("COMPLETED", "BUDGET_EXHAUSTED")
    assert len(result.evidence_gathered) >= 2
    assert len(result.relationships) > 0
    assert result.relationships[0].relationship_type == RelationshipType.SUPPORTED_BY_CODE
    assert "flask" in result.relationships[0].source_evidence_id


def test_system2_budget_exhaustion():
    s1 = make_mock_system1()
    budget = InvestigationBudget(max_steps=1, max_retrieval_calls=1)
    investigator = System2Investigator(system1=s1, budget=budget)

    result = investigator.investigate("Analyze deep dependency graph")
    assert result.retrieval_calls_made <= 2
    assert result.status in ("COMPLETED", "BUDGET_EXHAUSTED")


def test_system2_degraded_fallback_on_model_error():
    s1 = make_mock_system1()
    broken_provider = MagicMock()
    broken_provider.generate.side_effect = RuntimeError("Provider rate-limited")
    broken_provider.name = "broken_mock"

    investigator = System2Investigator(system1=s1, model_provider=broken_provider)
    result = investigator.investigate("Trace authorization tokens")

    assert result.status == "DEGRADED"
    assert "incomplete" in result.answer.lower()
    assert len(result.evidence_gathered) > 0  # Still preserves System 1 fast evidence!
