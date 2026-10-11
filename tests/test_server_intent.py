"""Tests for cross-repo intent detection in MCP server."""
import pytest
from infinite_memory.server import _detect_cross_repo_intent


class TestDetectCrossRepoIntent:
    def test_comparative_with_two_frameworks(self):
        assert _detect_cross_repo_intent("how does flask and fastapi handle routing") is True

    def test_vs_comparison(self):
        assert _detect_cross_repo_intent("express vs flask middleware") is True

    def test_across_frameworks(self):
        assert _detect_cross_repo_intent("error handling across flask and express") is True

    def test_single_framework_no_comparison(self):
        assert _detect_cross_repo_intent("flask routing decorator") is False

    def test_generic_query_no_frameworks(self):
        assert _detect_cross_repo_intent("how to parse JSON") is False

    def test_between_keyword(self):
        assert _detect_cross_repo_intent("differences between typescript and express") is True

    def test_both_keyword(self):
        assert _detect_cross_repo_intent("both flask and django use WSGI") is True

    def test_comparison_without_framework_names(self):
        assert _detect_cross_repo_intent("compare the two implementations") is False
