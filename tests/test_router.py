import pytest
from infinite_memory.core.router import SystemOneRouter, system_one_router


def test_router_ui_intent(mock_hub):
    mock_hub.register_project("webapp", "/path/to/webapp", "saas")
    router = SystemOneRouter(hub=mock_hub)
    res = router.route("What color is the logo in webapp header?")
    assert res["intent"] == "pinpoint_ui"
    assert res["target_project"] == "webapp"
    assert res["latency_ms"] < 10.0


def test_router_gateway_intent(mock_hub):
    mock_hub.register_project("gateway_svc", "/path/to/gateway", "gateway")
    router = SystemOneRouter(hub=mock_hub)
    res = router.route("Generate the master api key for gateway_svc")
    assert res["intent"] == "gateway_provision"
    assert res["target_project"] == "gateway_svc"


def test_router_cross_read_intent(mock_hub):
    mock_hub.register_project("app1", "/path/to/app1")
    mock_hub.register_project("app2", "/path/to/app2")
    router = SystemOneRouter(hub=mock_hub)
    res = router.route("Integrate video rendering across both projects")
    assert res["intent"] == "mesh_cross_read"
    assert res["target_project"] == "mesh_all"


def test_router_symbol_pinpoint(mock_hub):
    router = SystemOneRouter(hub=mock_hub)
    res = router.route("Inspect class NeuralMeshController in memory core")
    assert res["intent"] == "pinpoint_symbol"
    assert res["target_entity"] == "NeuralMeshController"


def test_router_latency_performance():
    res = system_one_router("Find database connection pooling logic")
    assert res["intent"] == "vector_search"
    assert res["latency_ms"] < 5.0
