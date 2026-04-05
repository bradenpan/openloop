"""Tests for Integration Builder MCP tool functions.

Tests call the async tool functions directly with a test DB session injected
via the _db parameter. This avoids needing SessionLocal() and the real database.
"""

import json

import pytest
from sqlalchemy.orm import Session
from unittest.mock import AsyncMock, MagicMock, patch

from backend.openloop.agents.mcp_tools import (
    create_api_data_source,
    create_sync_automation,
)
from backend.openloop.agents.mcp_tools import test_api_connection as _test_api_connection
from backend.openloop.services import agent_service, space_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(result: str) -> dict:
    """Parse a tool's JSON string return value."""
    return json.loads(result)


def _make_space(db: Session, name: str = "Test Space") -> str:
    """Create a space and return its ID."""
    space = space_service.create_space(db, name=name, template="project")
    return space.id


def _make_agent(db: Session, name: str = "Test Agent") -> str:
    """Create an agent and return its name."""
    agent = agent_service.create_agent(db, name=name, system_prompt="Test agent")
    return agent.name


async def _make_data_source(db: Session, space_id: str, name: str = "Test API") -> str:
    """Create an API data source via the tool and return its ID."""
    config = json.dumps({"base_url": "https://api.example.com", "endpoints": ["/data"]})
    result = _parse(await create_api_data_source(
        space_id=space_id, name=name, config=config, _db=db,
    ))
    return result["result"]["data_source_id"]


# ---------------------------------------------------------------------------
# create_api_data_source
# ---------------------------------------------------------------------------


class TestCreateApiDataSource:
    @pytest.mark.asyncio
    async def test_create_api_data_source_basic(self, db_session: Session):
        space_id = _make_space(db_session)
        config = json.dumps({
            "base_url": "https://api.example.com",
            "endpoints": ["/data"],
        })
        result = _parse(await create_api_data_source(
            space_id=space_id, name="Test API", config=config, _db=db_session,
        ))
        assert "result" in result
        assert result["result"]["name"] == "Test API"
        assert result["result"]["source_type"] == "api"
        assert result["result"]["status"] == "created"
        assert result["result"]["data_source_id"]

    @pytest.mark.asyncio
    async def test_create_api_data_source_with_auth(self, db_session: Session):
        space_id = _make_space(db_session)
        config = json.dumps({
            "base_url": "https://api.example.com",
            "auth_header_name": "Authorization",
            "auth_header_value": "Bearer secret-token",
            "endpoints": ["/data"],
        })
        result = _parse(await create_api_data_source(
            space_id=space_id, name="Auth API", config=config, _db=db_session,
        ))
        assert "result" in result
        ds_id = result["result"]["data_source_id"]

        # Verify the auth config was stored in the DB
        from backend.openloop.db.models import DataSource
        ds = db_session.query(DataSource).filter(DataSource.id == ds_id).first()
        assert ds is not None
        assert ds.config["auth_header_name"] == "Authorization"
        assert ds.config["auth_header_value"] == "Bearer secret-token"

    @pytest.mark.asyncio
    async def test_create_api_data_source_invalid_config(self, db_session: Session):
        space_id = _make_space(db_session)
        result = _parse(await create_api_data_source(
            space_id=space_id, name="Bad Config", config="not valid json{{{", _db=db_session,
        ))
        assert result["is_error"] is True
        assert "json" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_create_api_data_source_missing_base_url(self, db_session: Session):
        space_id = _make_space(db_session)
        config = json.dumps({"endpoints": ["/data"]})
        result = _parse(await create_api_data_source(
            space_id=space_id, name="No URL", config=config, _db=db_session,
        ))
        assert result["is_error"] is True
        assert "base_url" in result["error"]

    @pytest.mark.asyncio
    async def test_create_api_data_source_default_source_type(self, db_session: Session):
        space_id = _make_space(db_session)
        config = json.dumps({"base_url": "https://api.example.com"})
        # Pass empty source_type (or omit) — should default to "api"
        result = _parse(await create_api_data_source(
            space_id=space_id, name="Default Type", config=config,
            source_type="", _db=db_session,
        ))
        assert "result" in result
        assert result["result"]["source_type"] == "api"


# ---------------------------------------------------------------------------
# test_api_connection
# ---------------------------------------------------------------------------


class TestApiConnection:
    @pytest.mark.asyncio
    async def test_api_connection_success(self, db_session: Session):
        space_id = _make_space(db_session)
        ds_id = await _make_data_source(db_session, space_id)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok"}'
        mock_response.headers = {"content-type": "application/json"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _parse(await _test_api_connection(
                data_source_id=ds_id, _db=db_session,
            ))

        assert "result" in result
        assert result["result"]["status_code"] == 200
        assert "body_preview" in result["result"]
        assert "headers" in result["result"]
        assert result["result"]["url_tested"] == "https://api.example.com/data"

    @pytest.mark.asyncio
    async def test_api_connection_with_auth_headers(self, db_session: Session):
        space_id = _make_space(db_session)
        config = json.dumps({
            "base_url": "https://api.example.com",
            "auth_header_name": "X-API-Key",
            "auth_header_value": "my-secret-key",
            "endpoints": ["/secure"],
        })
        r = _parse(await create_api_data_source(
            space_id=space_id, name="Auth Source", config=config, _db=db_session,
        ))
        ds_id = r["result"]["data_source_id"]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await _test_api_connection(data_source_id=ds_id, _db=db_session)

        # Verify the auth header was sent
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        sent_headers = call_args.kwargs.get("headers", call_args[1].get("headers", {}))
        assert sent_headers.get("X-API-Key") == "my-secret-key"

    @pytest.mark.asyncio
    async def test_api_connection_body_truncation(self, db_session: Session):
        space_id = _make_space(db_session)
        ds_id = await _make_data_source(db_session, space_id)

        # Generate body > 2000 chars
        long_body = "x" * 3000
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = long_body
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _parse(await _test_api_connection(
                data_source_id=ds_id, _db=db_session,
            ))

        assert "result" in result
        assert len(result["result"]["body_preview"]) == 2000

    @pytest.mark.asyncio
    async def test_api_connection_invalid_data_source(self, db_session: Session):
        result = _parse(await _test_api_connection(
            data_source_id="nonexistent-id", _db=db_session,
        ))
        assert result["is_error"] is True
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_api_connection_http_error(self, db_session: Session):
        import httpx

        space_id = _make_space(db_session)
        ds_id = await _make_data_source(db_session, space_id)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused"),
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _parse(await _test_api_connection(
                data_source_id=ds_id, _db=db_session,
            ))

        assert result["is_error"] is True
        assert "connection" in result["error"].lower()


# ---------------------------------------------------------------------------
# create_sync_automation
# ---------------------------------------------------------------------------


class TestCreateSyncAutomation:
    @pytest.mark.asyncio
    async def test_create_sync_automation_basic(self, db_session: Session):
        space_id = _make_space(db_session)
        ds_id = await _make_data_source(db_session, space_id)
        agent_name = _make_agent(db_session, name="sync-agent")

        result = _parse(await create_sync_automation(
            data_source_id=ds_id,
            cron_expression="0 */6 * * *",
            agent_name=agent_name,
            instruction="Fetch latest data and store as items",
            name="My Sync Job",
            _db=db_session,
        ))

        assert "result" in result
        assert result["result"]["name"] == "My Sync Job"
        assert result["result"]["cron_expression"] == "0 */6 * * *"
        assert result["result"]["agent"] == agent_name
        assert result["result"]["data_source_id"] == ds_id
        assert result["result"]["status"] == "created"
        assert result["result"]["automation_id"]

    @pytest.mark.asyncio
    async def test_create_sync_automation_invalid_cron(self, db_session: Session):
        space_id = _make_space(db_session)
        ds_id = await _make_data_source(db_session, space_id)
        agent_name = _make_agent(db_session, name="cron-agent")

        result = _parse(await create_sync_automation(
            data_source_id=ds_id,
            cron_expression="not a valid cron",
            agent_name=agent_name,
            instruction="Fetch data",
            _db=db_session,
        ))

        assert result["is_error"] is True

    @pytest.mark.asyncio
    async def test_create_sync_automation_agent_not_found(self, db_session: Session):
        space_id = _make_space(db_session)
        ds_id = await _make_data_source(db_session, space_id)

        result = _parse(await create_sync_automation(
            data_source_id=ds_id,
            cron_expression="0 */6 * * *",
            agent_name="nonexistent-agent",
            instruction="Fetch data",
            _db=db_session,
        ))

        assert result["is_error"] is True
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_create_sync_automation_invalid_data_source(self, db_session: Session):
        agent_name = _make_agent(db_session, name="orphan-agent")

        result = _parse(await create_sync_automation(
            data_source_id="nonexistent-ds-id",
            cron_expression="0 */6 * * *",
            agent_name=agent_name,
            instruction="Fetch data",
            _db=db_session,
        ))

        assert result["is_error"] is True
        assert "not found" in result["error"].lower()


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    def test_integration_builder_tools_exclusive(self):
        """The 3 integration builder tools are in _INTEGRATION_BUILDER_TOOLS
        but not in _STANDARD_TOOLS."""
        from backend.openloop.agents.mcp_tools import (
            _INTEGRATION_BUILDER_TOOLS,
            _STANDARD_TOOLS,
        )

        exclusive_names = {"create_api_data_source", "test_api_connection", "create_sync_automation"}

        # All 3 are in the integration builder registry
        assert set(_INTEGRATION_BUILDER_TOOLS.keys()) == exclusive_names

        # None of them appear in the standard tool set
        for name in exclusive_names:
            assert name not in _STANDARD_TOOLS, (
                f"{name} should not be in _STANDARD_TOOLS"
            )
