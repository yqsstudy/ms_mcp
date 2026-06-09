import pytest
import pytest_asyncio

import cpp_client
from config import settings


@pytest_asyncio.fixture(autouse=True)
async def cleanup_client():
    yield
    await cpp_client.shutdown()


@pytest.mark.asyncio
async def test_initialise_uses_mock_client_without_websocket(monkeypatch):
    monkeypatch.setattr(settings, "cpp_mock_mode", True)

    async def fail_connect(*args, **kwargs):
        raise AssertionError("websockets.connect should not be called in mock mode")

    monkeypatch.setattr(cpp_client.websockets, "connect", fail_connect)

    client = await cpp_client.initialise()

    assert isinstance(client, cpp_client.MockCppBackendClient)
    assert client.is_connected
    assert cpp_client.backend_status()["mode"] == "mock"
    assert cpp_client.backend_status()["connected"] is True


@pytest.mark.asyncio
async def test_mock_heartcheck_response(monkeypatch):
    monkeypatch.setattr(settings, "cpp_mock_mode", True)
    client = await cpp_client.initialise()

    body = await client.request("heartCheck", "global")

    assert body["mock"] is True
    assert body["ok"] is True
    assert body["status"] == "OK"


@pytest.mark.asyncio
async def test_mock_unknown_command_fallback(monkeypatch):
    monkeypatch.setattr(settings, "cpp_mock_mode", True)
    client = await cpp_client.initialise()

    body = await client.request(
        "unknown/command",
        "unknown",
        params={"x": 1},
        project_name="project",
        file_id="file",
    )

    assert body["mock"] is True
    assert body["command"] == "unknown/command"
    assert body["moduleName"] == "unknown"
    assert body["params"] == {"x": 1}
    assert body["projectName"] == "project"
    assert body["fileId"] == "file"


@pytest.mark.asyncio
async def test_mock_cluster_fixtures_include_handler_fields(monkeypatch):
    monkeypatch.setattr(settings, "cpp_mock_mode", True)
    client = await cpp_client.initialise()

    iterations = await client.request("communication/duration/iterations", "communication")
    matrix = await client.request("communication/matrix/group", "communication")

    assert iterations["iterationOrRankId"]["compare"]
    assert matrix["data"][0]["groupIdHash"]["compare"]


@pytest.mark.asyncio
async def test_mock_import_fixture_contains_context_fields(monkeypatch):
    monkeypatch.setattr(settings, "cpp_mock_mode", True)
    client = await cpp_client.initialise()

    body = await client.request(
        "import/action",
        "timeline",
        params={"path": ["/tmp/mock.msprof"], "projectName": "debug_project"},
        project_name="debug_project",
    )

    assert body["mock"] is True
    assert body["success"] is True
    assert body["projectName"] == "debug_project"
    assert body["fileId"] == "/tmp/mock.msprof"
    assert body["clusterPath"] == "mock_cluster_path"
