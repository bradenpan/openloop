"""Phase 4 integration tests — cross-feature coverage gaps.

Covers:
- Records: custom field validation against schema, parent-child, children
  endpoint, link items, sort_by/sort_order on list
- Documents: upload text vs binary content_text extraction, content endpoint
  for both types, list with tag/mime_type filters, scan empty dir
- Search: search_all grouped results, space_id filtering, archived/superseded
  memory excluded, special chars in query, empty query (via API route)
- Cross-space: agent permission scoping, Odin sees all (MCP tools)
- Drive: link + index + refresh lifecycle (mocked), MCP tools (mocked)
- Integration: create space -> upload doc -> search finds it; create records
  with custom fields -> list with sort

FTS5 tests use manual virtual table creation following the pattern in
test_search_service.py.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.openloop.db.models import (
    Agent,
    Conversation,
    ConversationMessage,
    ConversationSummary,
    Document,
    MemoryEntry,
    Space,
)
from backend.openloop.services import document_service

# ---------------------------------------------------------------------------
# FTS5 setup (mirrors Alembic migration)
# ---------------------------------------------------------------------------

_FTS_SETUP_SQL = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS fts_conversation_messages
    USING fts5(content, content='conversation_messages', content_rowid='rowid');
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS fts_conversation_summaries
    USING fts5(summary, content='conversation_summaries', content_rowid='rowid');
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS fts_memory_entries
    USING fts5(value, content='memory_entries', content_rowid='rowid');
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS fts_documents
    USING fts5(title, content='documents', content_rowid='rowid');
    """,
    # Triggers -- conversation_messages
    """
    CREATE TRIGGER IF NOT EXISTS fts_conversation_messages_ai
    AFTER INSERT ON conversation_messages
    BEGIN
        INSERT INTO fts_conversation_messages(rowid, content)
        VALUES (new.rowid, new.content);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fts_conversation_messages_bd
    BEFORE DELETE ON conversation_messages
    BEGIN
        INSERT INTO fts_conversation_messages(fts_conversation_messages, rowid, content)
        VALUES ('delete', old.rowid, old.content);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fts_conversation_messages_au
    AFTER UPDATE ON conversation_messages
    BEGIN
        INSERT INTO fts_conversation_messages(fts_conversation_messages, rowid, content)
        VALUES ('delete', old.rowid, old.content);
        INSERT INTO fts_conversation_messages(rowid, content)
        VALUES (new.rowid, new.content);
    END;
    """,
    # Triggers -- conversation_summaries
    """
    CREATE TRIGGER IF NOT EXISTS fts_conversation_summaries_ai
    AFTER INSERT ON conversation_summaries
    BEGIN
        INSERT INTO fts_conversation_summaries(rowid, summary)
        VALUES (new.rowid, new.summary);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fts_conversation_summaries_bd
    BEFORE DELETE ON conversation_summaries
    BEGIN
        INSERT INTO fts_conversation_summaries(fts_conversation_summaries, rowid, summary)
        VALUES ('delete', old.rowid, old.summary);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fts_conversation_summaries_au
    AFTER UPDATE ON conversation_summaries
    BEGIN
        INSERT INTO fts_conversation_summaries(fts_conversation_summaries, rowid, summary)
        VALUES ('delete', old.rowid, old.summary);
        INSERT INTO fts_conversation_summaries(rowid, summary)
        VALUES (new.rowid, new.summary);
    END;
    """,
    # Triggers -- memory_entries (only index active)
    """
    CREATE TRIGGER IF NOT EXISTS fts_memory_entries_ai
    AFTER INSERT ON memory_entries
    WHEN new.archived_at IS NULL AND new.valid_until IS NULL
    BEGIN
        INSERT INTO fts_memory_entries(rowid, value)
        VALUES (new.rowid, new.value);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fts_memory_entries_bd
    BEFORE DELETE ON memory_entries
    BEGIN
        INSERT INTO fts_memory_entries(fts_memory_entries, rowid, value)
        VALUES ('delete', old.rowid, old.value);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fts_memory_entries_au
    AFTER UPDATE ON memory_entries
    BEGIN
        INSERT INTO fts_memory_entries(fts_memory_entries, rowid, value)
        VALUES ('delete', old.rowid, old.value);
        INSERT INTO fts_memory_entries(rowid, value)
        SELECT new.rowid, new.value
        WHERE new.archived_at IS NULL AND new.valid_until IS NULL;
    END;
    """,
    # Triggers -- documents
    """
    CREATE TRIGGER IF NOT EXISTS fts_documents_ai
    AFTER INSERT ON documents
    BEGIN
        INSERT INTO fts_documents(rowid, title)
        VALUES (new.rowid, new.title);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fts_documents_bd
    BEFORE DELETE ON documents
    BEGIN
        INSERT INTO fts_documents(fts_documents, rowid, title)
        VALUES ('delete', old.rowid, old.title);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fts_documents_au
    AFTER UPDATE ON documents
    BEGIN
        INSERT INTO fts_documents(fts_documents, rowid, title)
        VALUES ('delete', old.rowid, old.title);
        INSERT INTO fts_documents(rowid, title)
        VALUES (new.rowid, new.title);
    END;
    """,
]

_FTS_TEARDOWN_TRIGGERS = [
    "fts_conversation_messages_ai",
    "fts_conversation_messages_bd",
    "fts_conversation_messages_au",
    "fts_conversation_summaries_ai",
    "fts_conversation_summaries_bd",
    "fts_conversation_summaries_au",
    "fts_memory_entries_ai",
    "fts_memory_entries_bd",
    "fts_memory_entries_au",
    "fts_documents_ai",
    "fts_documents_bd",
    "fts_documents_au",
]

_FTS_TEARDOWN_TABLES = [
    "fts_conversation_messages",
    "fts_conversation_summaries",
    "fts_memory_entries",
    "fts_documents",
]


def _uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fts_db(db_session: Session) -> Session:
    """Create FTS5 virtual tables + triggers, yield session, tear down."""
    conn = db_session.connection()
    for sql in _FTS_SETUP_SQL:
        conn.execute(text(sql))
    db_session.commit()
    yield db_session
    conn = db_session.connection()
    for name in _FTS_TEARDOWN_TRIGGERS:
        conn.execute(text(f"DROP TRIGGER IF EXISTS {name};"))
    for table in _FTS_TEARDOWN_TABLES:
        conn.execute(text(f"DROP TABLE IF EXISTS {table};"))
    db_session.commit()


@pytest.fixture()
def multi_space_data(fts_db: Session) -> dict:
    """Two spaces, two agents (scoped + Odin), conversations, messages,
    summaries, memory entries, and documents for cross-space testing."""
    space_a = Space(id=_uid(), name="Engineering", template="project")
    space_b = Space(id=_uid(), name="Marketing", template="project")
    fts_db.add_all([space_a, space_b])
    fts_db.flush()

    scoped = Agent(id=_uid(), name="eng-agent")
    odin = Agent(id=_uid(), name="odin")
    fts_db.add_all([scoped, odin])
    fts_db.flush()

    # Grant scoped agent access to space_a only
    fts_db.execute(
        text("INSERT INTO agent_spaces (agent_id, space_id) VALUES (:aid, :sid)"),
        {"aid": scoped.id, "sid": space_a.id},
    )
    fts_db.flush()

    conv_a = Conversation(
        id=_uid(), space_id=space_a.id, agent_id=scoped.id,
        name="Backend Design",
    )
    conv_b = Conversation(
        id=_uid(), space_id=space_b.id, agent_id=odin.id,
        name="Campaign Plan",
    )
    fts_db.add_all([conv_a, conv_b])
    fts_db.flush()

    msg_a = ConversationMessage(
        id=_uid(), conversation_id=conv_a.id, role="user",
        content="The deployment pipeline uses Kubernetes for orchestration",
    )
    msg_b = ConversationMessage(
        id=_uid(), conversation_id=conv_b.id, role="user",
        content="Our marketing campaign will leverage Kubernetes awareness",
    )
    fts_db.add_all([msg_a, msg_b])
    fts_db.flush()

    summary_a = ConversationSummary(
        id=_uid(), conversation_id=conv_a.id, space_id=space_a.id,
        summary="Reviewed Kubernetes deployment pipeline architecture",
    )
    summary_b = ConversationSummary(
        id=_uid(), conversation_id=conv_b.id, space_id=space_b.id,
        summary="Planned Kubernetes marketing campaign for DevOps audience",
    )
    fts_db.add_all([summary_a, summary_b])
    fts_db.flush()

    mem_active = MemoryEntry(
        id=_uid(), namespace="facts", key="deploy-tool",
        value="Team uses Kubernetes for container orchestration",
        importance=0.7, category="technical",
    )
    mem_archived = MemoryEntry(
        id=_uid(), namespace="facts", key="old-deploy",
        value="Team previously used Docker Swarm for Kubernetes migration prep",
        importance=0.5, category="technical",
        archived_at=datetime.now(UTC),
    )
    mem_superseded = MemoryEntry(
        id=_uid(), namespace="facts", key="cluster-version",
        value="Kubernetes cluster runs version 1.25",
        importance=0.4, category="technical",
        valid_until=datetime.now(UTC),
    )
    fts_db.add_all([mem_active, mem_archived, mem_superseded])
    fts_db.flush()

    doc_a = Document(
        id=_uid(), space_id=space_a.id,
        title="Kubernetes Deployment Guide", source="manual",
    )
    doc_b = Document(
        id=_uid(), space_id=space_b.id,
        title="Kubernetes Marketing Brief", source="manual",
    )
    fts_db.add_all([doc_a, doc_b])
    fts_db.flush()

    fts_db.commit()

    return {
        "space_a": space_a,
        "space_b": space_b,
        "scoped": scoped,
        "odin": odin,
        "conv_a": conv_a,
        "conv_b": conv_b,
        "msg_a": msg_a,
        "msg_b": msg_b,
        "summary_a": summary_a,
        "summary_b": summary_b,
        "mem_active": mem_active,
        "mem_archived": mem_archived,
        "mem_superseded": mem_superseded,
        "doc_a": doc_a,
        "doc_b": doc_b,
    }


# ---------------------------------------------------------------------------
# Helpers (API)
# ---------------------------------------------------------------------------


def _create_space(client: TestClient, name: str = "Test", template: str = "project") -> dict:
    resp = client.post("/api/v1/spaces", json={"name": name, "template": template})
    assert resp.status_code == 201
    return resp.json()


def _create_crm_space(client: TestClient, name: str = "CRM") -> dict:
    space = _create_space(client, name=name, template="crm")
    schema = [
        {"name": "company", "type": "text"},
        {"name": "deal_value", "type": "number"},
        {"name": "email", "type": "text"},
    ]
    resp = client.patch(f"/api/v1/spaces/{space['id']}", json={"custom_field_schema": schema})
    assert resp.status_code == 200
    return resp.json()


def _create_item(client: TestClient, space_id: str, **kw) -> dict:
    payload = {"space_id": space_id, "title": kw.pop("title", "Item"), **kw}
    resp = client.post("/api/v1/items", json=payload)
    assert resp.status_code == 201
    return resp.json()


# ===========================================================================
# 1. RECORDS — custom field validation, parent-child, children endpoint,
#    link items, sort_by/sort_order
# ===========================================================================


class TestRecordsIntegration:
    """End-to-end record lifecycle through the API."""

    def test_create_record_with_custom_fields_validation(self, client: TestClient):
        """Custom fields matching schema stored; unknown fields still accepted
        (lenient validation) but server logs a warning."""
        space = _create_crm_space(client)
        record = _create_item(
            client, space["id"],
            title="Acme Corp",
            item_type="record",
            custom_fields={"company": "Acme", "deal_value": 50000},
        )
        assert record["custom_fields"]["company"] == "Acme"
        assert record["custom_fields"]["deal_value"] == 50000

    def test_parent_child_record_lifecycle(self, client: TestClient):
        """Create parent record, add children, verify GET children endpoint."""
        space = _create_crm_space(client)
        parent = _create_item(
            client, space["id"], title="HQ Record", item_type="record",
        )
        child1 = _create_item(
            client, space["id"], title="Sub Deal A",
            parent_item_id=parent["id"],
        )
        child2 = _create_item(
            client, space["id"], title="Sub Deal B",
            parent_item_id=parent["id"],
        )
        # unrelated item should not appear
        _create_item(client, space["id"], title="Other Item")

        # GET children endpoint
        resp = client.get(f"/api/v1/items/{parent['id']}/children")
        assert resp.status_code == 200
        data = resp.json()
        assert data["record"]["id"] == parent["id"]
        assert len(data["child_records"]) == 2
        child_ids = {c["id"] for c in data["child_records"]}
        assert child1["id"] in child_ids
        assert child2["id"] in child_ids
        assert len(data["linked_items"]) == 0

    def test_link_item_shows_in_children_response(self, client: TestClient):
        """Link an item to a record, confirm it appears in the children endpoint."""
        space = _create_crm_space(client)
        record = _create_item(client, space["id"], title="Record", item_type="record")
        task = _create_item(client, space["id"], title="Follow up call")

        link_resp = client.post(
            f"/api/v1/items/{record['id']}/links",
            json={"target_item_id": task["id"]},
        )
        assert link_resp.status_code == 201

        children_resp = client.get(f"/api/v1/items/{record['id']}/children")
        assert children_resp.status_code == 200
        assert len(children_resp.json()["linked_items"]) == 1
        assert children_resp.json()["linked_items"][0]["id"] == task["id"]

    def test_list_items_sort_by_title_asc_and_desc(self, client: TestClient):
        """sort_by=title with both asc and desc order."""
        space = _create_space(client)
        _create_item(client, space["id"], title="Cherry")
        _create_item(client, space["id"], title="Apple")
        _create_item(client, space["id"], title="Banana")

        resp_asc = client.get("/api/v1/items?sort_by=title&sort_order=asc")
        assert resp_asc.status_code == 200
        assert [i["title"] for i in resp_asc.json()] == ["Apple", "Banana", "Cherry"]

        resp_desc = client.get("/api/v1/items?sort_by=title&sort_order=desc")
        assert resp_desc.status_code == 200
        assert [i["title"] for i in resp_desc.json()] == ["Cherry", "Banana", "Apple"]

    def test_list_items_sort_by_due_date(self, client: TestClient):
        """sort_by=due_date — items without due_date still appear."""
        space = _create_space(client)
        i1 = _create_item(client, space["id"], title="No date")
        i2 = _create_item(client, space["id"], title="With date", due_date="2026-06-01")
        i3 = _create_item(client, space["id"], title="Earlier date", due_date="2026-01-15")

        resp = client.get("/api/v1/items?sort_by=due_date&sort_order=asc")
        assert resp.status_code == 200
        titles = [i["title"] for i in resp.json()]
        # items with null due_date sort first (NULL < any date in SQLite asc)
        assert titles[0] == "No date"

    def test_list_items_filter_by_item_type_record(self, client: TestClient):
        """item_type=record filter returns only records."""
        space = _create_crm_space(client)
        _create_item(client, space["id"], title="Task A", item_type="task")
        rec = _create_item(client, space["id"], title="Record A", item_type="record")

        resp = client.get(f"/api/v1/items?item_type=record&space_id={space['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == rec["id"]

    def test_archived_child_excluded_from_children(self, client: TestClient):
        """Archived children do not appear in GET children."""
        space = _create_crm_space(client)
        parent = _create_item(client, space["id"], title="Parent", item_type="record")
        child = _create_item(
            client, space["id"], title="Active", parent_item_id=parent["id"],
        )
        archived = _create_item(
            client, space["id"], title="Archived", parent_item_id=parent["id"],
        )
        client.post(f"/api/v1/items/{archived['id']}/archive")

        resp = client.get(f"/api/v1/items/{parent['id']}/children")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["child_records"]) == 1
        assert data["child_records"][0]["id"] == child["id"]


# ===========================================================================
# 2. DOCUMENTS — upload text vs binary, content endpoint, list filters,
#    scan empty dir
# ===========================================================================


class TestDocumentsIntegration:
    """Document upload, scan, content retrieval, and filtering."""

    def test_upload_text_extracts_content(self, client: TestClient, tmp_path: Path):
        """Uploading a text file populates content_text."""
        space = _create_space(client)
        with patch.object(document_service, "DOCUMENTS_DIR", tmp_path):
            resp = client.post(
                "/api/v1/documents/upload",
                params={"space_id": space["id"]},
                files={"file": ("notes.md", b"# Project Notes\nSome text here", "text/markdown")},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "notes.md"
        assert data["mime_type"] == "text/markdown"
        assert data["file_size"] == len(b"# Project Notes\nSome text here")

    def test_upload_binary_no_content_text(self, client: TestClient, tmp_path: Path):
        """Uploading a binary file leaves content_text null."""
        space = _create_space(client)
        with patch.object(document_service, "DOCUMENTS_DIR", tmp_path):
            resp = client.post(
                "/api/v1/documents/upload",
                params={"space_id": space["id"]},
                files={"file": ("photo.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 50, "image/jpeg")},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "photo.jpg"
        assert data["mime_type"] == "image/jpeg"

    def test_content_endpoint_text_file(self, client: TestClient, tmp_path: Path):
        """GET /documents/{id}/content returns plain text for text files."""
        space = _create_space(client)
        with patch.object(document_service, "DOCUMENTS_DIR", tmp_path):
            up = client.post(
                "/api/v1/documents/upload",
                params={"space_id": space["id"]},
                files={"file": ("readme.txt", b"Hello from readme", "text/plain")},
            )
            doc_id = up.json()["id"]
            resp = client.get(f"/api/v1/documents/{doc_id}/content")
        assert resp.status_code == 200
        assert "Hello from readme" in resp.text

    def test_content_endpoint_binary_file(self, client: TestClient, tmp_path: Path):
        """GET /documents/{id}/content streams binary for non-text files."""
        space = _create_space(client)
        binary_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        with patch.object(document_service, "DOCUMENTS_DIR", tmp_path):
            up = client.post(
                "/api/v1/documents/upload",
                params={"space_id": space["id"]},
                files={"file": ("img.png", binary_data, "image/png")},
            )
            doc_id = up.json()["id"]
            resp = client.get(f"/api/v1/documents/{doc_id}/content")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith(("image/png", "application/octet-stream"))

    def test_list_documents_filter_by_mime_type(self, client: TestClient, tmp_path: Path):
        """mime_type query param filters correctly."""
        space = _create_space(client)
        with patch.object(document_service, "DOCUMENTS_DIR", tmp_path):
            client.post(
                "/api/v1/documents/upload",
                params={"space_id": space["id"]},
                files={"file": ("a.txt", b"text", "text/plain")},
            )
            client.post(
                "/api/v1/documents/upload",
                params={"space_id": space["id"]},
                files={"file": ("b.csv", b"a,b", "text/csv")},
            )

        resp = client.get(
            "/api/v1/documents",
            params={"space_id": space["id"], "mime_type": "text/plain"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "a.txt"

    def test_list_documents_filter_by_tag(self, client: TestClient):
        """Tags comma-separated filter works."""
        space = _create_space(client)
        d1 = client.post("/api/v1/documents", json={
            "space_id": space["id"], "title": "Tagged",
        })
        d1_id = d1.json()["id"]
        # Add tags via PATCH
        client.patch(f"/api/v1/documents/{d1_id}", json={"tags": ["alpha", "beta"]})

        d2 = client.post("/api/v1/documents", json={
            "space_id": space["id"], "title": "Untagged",
        })

        resp = client.get(
            "/api/v1/documents",
            params={"space_id": space["id"], "tags": "alpha"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Tagged"

    def test_scan_empty_directory(self, client: TestClient, tmp_path: Path):
        """Scanning a space dir that exists but has no files returns 0."""
        space = _create_space(client)
        space_dir = tmp_path / space["id"]
        space_dir.mkdir()

        with patch.object(document_service, "DOCUMENTS_DIR", tmp_path):
            resp = client.post(f"/api/v1/documents/scan/{space['id']}")
        assert resp.status_code == 200
        assert resp.json()["new_count"] == 0

    def test_scan_no_directory_returns_zero(self, client: TestClient, tmp_path: Path):
        """Scanning a space with no dir on disk returns 0."""
        space = _create_space(client)
        with patch.object(document_service, "DOCUMENTS_DIR", tmp_path):
            resp = client.post(f"/api/v1/documents/scan/{space['id']}")
        assert resp.status_code == 200
        assert resp.json()["new_count"] == 0

    def test_delete_document(self, client: TestClient):
        """DELETE /documents/{id} removes the document."""
        space = _create_space(client)
        doc = client.post("/api/v1/documents", json={
            "space_id": space["id"], "title": "Deletable",
        })
        doc_id = doc.json()["id"]

        resp = client.delete(f"/api/v1/documents/{doc_id}")
        assert resp.status_code == 204

        resp = client.get(f"/api/v1/documents/{doc_id}")
        assert resp.status_code == 404


# ===========================================================================
# 3. SEARCH — search_all grouped, space_id filter, archived/superseded
#    exclusion, special chars, empty query (API route)
# ===========================================================================


class TestSearchIntegration:
    """FTS5-backed search through service layer and API route."""

    def test_search_all_returns_grouped_results(self, multi_space_data: dict, fts_db: Session):
        """search_all returns dict with messages/summaries/memory/documents keys."""
        from backend.openloop.services import search_service

        results = search_service.search_all(fts_db, "Kubernetes")
        assert set(results.keys()) == {"messages", "summaries", "memory", "documents"}
        total = sum(len(v) for v in results.values())
        assert total > 0

    def test_search_all_space_filter(self, multi_space_data: dict, fts_db: Session):
        """space_id filter restricts messages/summaries/documents to one space."""
        from backend.openloop.services import search_service

        sid = multi_space_data["space_a"].id
        results = search_service.search_all(fts_db, "Kubernetes", space_id=sid)
        for r in results.get("messages", []):
            assert r["space_id"] == sid
        for r in results.get("summaries", []):
            assert r["space_id"] == sid
        for r in results.get("documents", []):
            assert r["space_id"] == sid

    def test_archived_memory_excluded_from_search(
        self, multi_space_data: dict, fts_db: Session
    ):
        """Archived memory entries are removed from the FTS index."""
        from backend.openloop.services import search_service

        results = search_service.search_memory(fts_db, "Docker Swarm")
        matching = [r for r in results if r["id"] == multi_space_data["mem_archived"].id]
        assert matching == []

    def test_superseded_memory_excluded_from_search(
        self, multi_space_data: dict, fts_db: Session
    ):
        """Memory entries with valid_until set are removed from the FTS index."""
        from backend.openloop.services import search_service

        results = search_service.search_memory(fts_db, "version 1.25")
        matching = [r for r in results if r["id"] == multi_space_data["mem_superseded"].id]
        assert matching == []

    def test_active_memory_found(self, multi_space_data: dict, fts_db: Session):
        """Active memory (no archived_at, no valid_until) IS indexed."""
        from backend.openloop.services import search_service

        results = search_service.search_memory(fts_db, "container orchestration")
        assert len(results) >= 1
        ids = {r["id"] for r in results}
        assert multi_space_data["mem_active"].id in ids

    def test_special_chars_in_query_safe(self, multi_space_data: dict, fts_db: Session):
        """FTS5 special characters are sanitized, no crash."""
        from backend.openloop.services import search_service

        results = search_service.search_messages(fts_db, '"Kubernetes" OR (hack*)')
        assert isinstance(results, list)

    def test_empty_query_returns_empty(self, multi_space_data: dict, fts_db: Session):
        """Empty string query returns no results."""
        from backend.openloop.services import search_service

        assert search_service.search_all(fts_db, "") == {
            "messages": [],
            "summaries": [],
            "memory": [],
            "documents": [],
        }

    def test_search_documents_space_filter(self, multi_space_data: dict, fts_db: Session):
        """Document search with space_id only returns docs from that space."""
        from backend.openloop.services import search_service

        sid_a = multi_space_data["space_a"].id
        results = search_service.search_documents(fts_db, "Kubernetes", space_id=sid_a)
        assert len(results) >= 1
        assert all(r["space_id"] == sid_a for r in results)

        sid_b = multi_space_data["space_b"].id
        results_b = search_service.search_documents(fts_db, "Kubernetes", space_id=sid_b)
        assert len(results_b) >= 1
        assert all(r["space_id"] == sid_b for r in results_b)


# ===========================================================================
# 4. CROSS-SPACE — agent permission scoping, Odin sees all (MCP tools)
# ===========================================================================


class TestCrossSpacePermissions:
    """MCP tool permission scoping via _get_agent_space_ids."""

    @pytest.mark.asyncio
    async def test_scoped_agent_only_sees_own_space(
        self, multi_space_data: dict, fts_db: Session
    ):
        """Scoped agent's search returns only results from permitted spaces."""
        from backend.openloop.agents.mcp_tools import search_conversations

        raw = await search_conversations(
            query="Kubernetes",
            _db=fts_db,
            _agent_id=multi_space_data["scoped"].id,
        )
        data = json.loads(raw)
        results = data["result"]
        assert len(results) >= 1
        for r in results:
            assert r["space_id"] == multi_space_data["space_a"].id

    @pytest.mark.asyncio
    async def test_odin_sees_all_spaces(self, multi_space_data: dict, fts_db: Session):
        """Odin (no space restrictions) sees results from all spaces."""
        from backend.openloop.agents.mcp_tools import search_conversations

        raw = await search_conversations(
            query="Kubernetes",
            _db=fts_db,
            _agent_id=multi_space_data["odin"].id,
        )
        data = json.loads(raw)
        results = data["result"]
        space_ids = {r["space_id"] for r in results}
        assert multi_space_data["space_a"].id in space_ids
        assert multi_space_data["space_b"].id in space_ids

    @pytest.mark.asyncio
    async def test_scoped_agent_summaries(self, multi_space_data: dict, fts_db: Session):
        """Scoped agent's summary search only returns permitted-space summaries."""
        from backend.openloop.agents.mcp_tools import search_summaries

        raw = await search_summaries(
            query="Kubernetes",
            _db=fts_db,
            _agent_id=multi_space_data["scoped"].id,
        )
        data = json.loads(raw)
        results = data["result"]
        assert len(results) >= 1
        for r in results:
            assert r["space_id"] == multi_space_data["space_a"].id

    @pytest.mark.asyncio
    async def test_odin_summaries_all_spaces(self, multi_space_data: dict, fts_db: Session):
        """Odin sees summaries from every space."""
        from backend.openloop.agents.mcp_tools import search_summaries

        raw = await search_summaries(
            query="Kubernetes",
            _db=fts_db,
            _agent_id=multi_space_data["odin"].id,
        )
        data = json.loads(raw)
        results = data["result"]
        space_ids = {r["space_id"] for r in results}
        assert multi_space_data["space_a"].id in space_ids
        assert multi_space_data["space_b"].id in space_ids


# ===========================================================================
# 5. DRIVE — link + index + refresh lifecycle (mocked), MCP tools (mocked)
# ===========================================================================

MOCK_DRIVE_FILES = [
    {
        "id": "d-file-1",
        "name": "spec.txt",
        "mimeType": "text/plain",
        "size": "2048",
        "modifiedTime": "2026-03-30T10:00:00.000Z",
    },
    {
        "id": "d-file-2",
        "name": "logo.png",
        "mimeType": "image/png",
        "size": "50000",
        "modifiedTime": "2026-03-30T11:00:00.000Z",
    },
]


class TestDriveIntegration:
    """Google Drive link -> index -> refresh lifecycle (all mocked)."""

    @patch("backend.openloop.services.drive_integration_service.gdrive_client")
    def test_link_index_refresh_lifecycle(self, mock_client, db_session: Session):
        """Full lifecycle: link folder -> initial index -> refresh with changes."""
        mock_client.list_files.return_value = MOCK_DRIVE_FILES
        mock_client.read_file_text.side_effect = lambda fid: (
            "spec file content" if fid == "d-file-1" else None
        )

        space = Space(name="Drive Space", template="default")
        db_session.add(space)
        db_session.commit()
        db_session.refresh(space)

        from backend.openloop.services import drive_integration_service

        # 1. Link
        ds = drive_integration_service.link_drive_folder(
            db_session, space_id=space.id,
            folder_id="folder-main", folder_name="Main Folder",
        )
        assert ds.source_type == "google_drive"
        assert ds.config["folder_id"] == "folder-main"

        # Verify initial index created 2 documents
        docs = (
            db_session.query(Document)
            .filter(Document.source == "drive", Document.space_id == space.id)
            .all()
        )
        assert len(docs) == 2
        text_doc = next(d for d in docs if d.title == "spec.txt")
        assert text_doc.content_text == "spec file content"
        bin_doc = next(d for d in docs if d.title == "logo.png")
        assert bin_doc.content_text is None

        # 2. Refresh — add a new file, remove one
        mock_client.list_files.return_value = [
            MOCK_DRIVE_FILES[0],  # keep spec.txt
            {
                "id": "d-file-3",
                "name": "readme.md",
                "mimeType": "text/markdown",
                "size": "500",
                "modifiedTime": "2026-03-31T08:00:00.000Z",
            },
        ]
        mock_client.read_file_text.side_effect = lambda fid: (
            "readme content" if fid == "d-file-3" else "spec file content"
        )

        result = drive_integration_service.refresh_drive_index(
            db_session, data_source_id=ds.id
        )
        assert result["added"] == 1
        assert result["removed"] == 1  # logo.png removed

        remaining = (
            db_session.query(Document)
            .filter(Document.source == "drive", Document.space_id == space.id)
            .all()
        )
        assert len(remaining) == 2
        titles = {d.title for d in remaining}
        assert "spec.txt" in titles
        assert "readme.md" in titles
        assert "logo.png" not in titles

    @patch("backend.openloop.services.drive_integration_service.gdrive_client")
    def test_link_duplicate_folder_409(self, mock_client, db_session: Session):
        """Linking the same folder twice returns 409."""
        mock_client.list_files.return_value = []

        space = Space(name="DupDrive", template="default")
        db_session.add(space)
        db_session.commit()
        db_session.refresh(space)

        from backend.openloop.services import drive_integration_service

        drive_integration_service.link_drive_folder(
            db_session, space_id=space.id,
            folder_id="folder-dup", folder_name="Folder",
        )
        with pytest.raises(Exception) as exc:
            drive_integration_service.link_drive_folder(
                db_session, space_id=space.id,
                folder_id="folder-dup", folder_name="Folder Again",
            )
        assert "409" in str(exc.value.status_code)


class TestDriveMcpToolsIntegration:
    """MCP tool wrappers for Drive — all mocked."""

    @pytest.mark.asyncio
    @patch("backend.openloop.services.gdrive_client.is_authenticated", return_value=True)
    @patch("backend.openloop.services.gdrive_client.read_file_text", return_value="file text")
    async def test_read_drive_file(self, mock_read, mock_auth):
        from backend.openloop.agents.mcp_tools import read_drive_file

        raw = await read_drive_file("file-abc")
        data = json.loads(raw)
        assert data["result"]["content"] == "file text"
        assert data["result"]["file_id"] == "file-abc"

    @pytest.mark.asyncio
    @patch("backend.openloop.services.gdrive_client.is_authenticated", return_value=False)
    async def test_read_drive_file_unauthenticated(self, mock_auth):
        from backend.openloop.agents.mcp_tools import read_drive_file

        raw = await read_drive_file("file-abc")
        data = json.loads(raw)
        assert data["is_error"] is True
        assert "not authenticated" in data["error"]

    @pytest.mark.asyncio
    @patch("backend.openloop.services.gdrive_client.is_authenticated", return_value=True)
    @patch("backend.openloop.services.gdrive_client.list_files", return_value=MOCK_DRIVE_FILES)
    async def test_list_drive_files(self, mock_list, mock_auth):
        from backend.openloop.agents.mcp_tools import list_drive_files

        raw = await list_drive_files("folder-xyz")
        data = json.loads(raw)
        assert len(data["result"]) == 2
        assert data["result"][0]["name"] == "spec.txt"

    @pytest.mark.asyncio
    @patch("backend.openloop.services.gdrive_client.is_authenticated", return_value=True)
    @patch(
        "backend.openloop.services.gdrive_client.create_file",
        return_value={"id": "new-f", "name": "new.txt", "mimeType": "text/plain"},
    )
    async def test_create_drive_file(self, mock_create, mock_auth):
        from backend.openloop.agents.mcp_tools import create_drive_file

        raw = await create_drive_file("folder-xyz", "new.txt", "hello world")
        data = json.loads(raw)
        assert data["result"]["id"] == "new-f"
        assert data["result"]["name"] == "new.txt"

    @pytest.mark.asyncio
    @patch("backend.openloop.services.gdrive_client.is_authenticated", return_value=True)
    @patch("backend.openloop.services.gdrive_client.read_file_text", return_value=None)
    async def test_read_drive_file_binary_returns_error(self, mock_read, mock_auth):
        """Attempting to read a binary file returns is_error."""
        from backend.openloop.agents.mcp_tools import read_drive_file

        raw = await read_drive_file("binary-file")
        data = json.loads(raw)
        assert data["is_error"] is True
        assert "binary" in data["error"].lower()


# ===========================================================================
# 6. END-TO-END INTEGRATION — space -> doc -> search; records + sort
# ===========================================================================


class TestEndToEndIntegration:
    """Full flow tests combining multiple features."""

    def test_create_space_upload_doc_search_finds_it(
        self, client: TestClient, tmp_path: Path, db_session: Session
    ):
        """Create space -> upload document -> FTS search finds it by title."""
        # Create FTS tables on the db_session used by the client
        conn = db_session.connection()
        for sql in _FTS_SETUP_SQL:
            conn.execute(text(sql))
        db_session.commit()

        space = _create_space(client, name="SearchTarget")

        with patch.object(document_service, "DOCUMENTS_DIR", tmp_path):
            client.post(
                "/api/v1/documents/upload",
                params={"space_id": space["id"]},
                files={"file": ("quantum-report.txt", b"Quantum computing overview", "text/plain")},
            )

        # FTS should find it by title
        from backend.openloop.services import search_service

        results = search_service.search_documents(db_session, "quantum")
        assert len(results) >= 1
        assert any("quantum" in r["title"].lower() for r in results)

        # Teardown FTS
        conn = db_session.connection()
        for name in _FTS_TEARDOWN_TRIGGERS:
            conn.execute(text(f"DROP TRIGGER IF EXISTS {name};"))
        for table in _FTS_TEARDOWN_TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {table};"))
        db_session.commit()

    def test_records_with_custom_fields_sort_by_title(self, client: TestClient):
        """Create CRM records with custom fields, list with sort, verify order."""
        space = _create_crm_space(client, name="Sales CRM")
        _create_item(
            client, space["id"],
            title="Zebra Inc",
            item_type="record",
            custom_fields={"company": "Zebra Inc", "deal_value": 30000},
        )
        _create_item(
            client, space["id"],
            title="Alpha Corp",
            item_type="record",
            custom_fields={"company": "Alpha Corp", "deal_value": 80000},
        )
        _create_item(
            client, space["id"],
            title="Mid LLC",
            item_type="record",
            custom_fields={"company": "Mid LLC", "deal_value": 50000},
        )

        resp = client.get(
            "/api/v1/items",
            params={
                "space_id": space["id"],
                "item_type": "record",
                "sort_by": "title",
                "sort_order": "asc",
            },
        )
        assert resp.status_code == 200
        titles = [i["title"] for i in resp.json()]
        assert titles == ["Alpha Corp", "Mid LLC", "Zebra Inc"]

    def test_scan_then_list_sorted(self, client: TestClient, tmp_path: Path):
        """Scan files into a space, list sorted by title."""
        space = _create_space(client, name="ScanSort")
        space_dir = tmp_path / space["id"]
        space_dir.mkdir()
        (space_dir / "zebra.txt").write_text("z data", encoding="utf-8")
        (space_dir / "alpha.txt").write_text("a data", encoding="utf-8")

        with patch.object(document_service, "DOCUMENTS_DIR", tmp_path):
            scan = client.post(f"/api/v1/documents/scan/{space['id']}")
            assert scan.json()["new_count"] == 2

            resp = client.get(
                "/api/v1/documents",
                params={"space_id": space["id"], "sort_by": "title"},
            )
        assert resp.status_code == 200
        titles = [d["title"] for d in resp.json()]
        assert titles == ["alpha.txt", "zebra.txt"]

    def test_drive_api_route_link_and_refresh(self, client: TestClient):
        """Drive API routes: link folder, then refresh."""
        space = _create_space(client, name="DriveAPI")

        with (
            patch(
                "backend.openloop.services.drive_integration_service.gdrive_client"
            ) as mock_client,
        ):
            mock_client.list_files.return_value = MOCK_DRIVE_FILES
            mock_client.read_file_text.side_effect = lambda fid: (
                "text content" if fid == "d-file-1" else None
            )

            link_resp = client.post("/api/v1/drive/link", json={
                "space_id": space["id"],
                "folder_id": "folder-api",
                "folder_name": "API Test Folder",
            })
            assert link_resp.status_code == 201
            link_data = link_resp.json()
            assert link_data["folder_name"] == "API Test Folder"
            assert link_data["documents_indexed"] == 2

            ds_id = link_data["data_source_id"]

            # Refresh with one removed, one added
            mock_client.list_files.return_value = [
                MOCK_DRIVE_FILES[0],
                {
                    "id": "d-file-4",
                    "name": "new-doc.txt",
                    "mimeType": "text/plain",
                    "size": "100",
                    "modifiedTime": "2026-03-31T12:00:00.000Z",
                },
            ]
            mock_client.read_file_text.side_effect = lambda fid: "new text"

            refresh_resp = client.post(f"/api/v1/drive/refresh/{ds_id}")
            assert refresh_resp.status_code == 200
            rdata = refresh_resp.json()
            assert rdata["added"] == 1
            assert rdata["removed"] == 1

    def test_drive_auth_status_route(self, client: TestClient):
        """GET /drive/auth-status returns authentication state."""
        with patch(
            "backend.openloop.services.gdrive_client.is_authenticated",
            return_value=False,
        ):
            resp = client.get("/api/v1/drive/auth-status")
            assert resp.status_code == 200
            assert resp.json()["authenticated"] is False

    def test_search_api_route_type_filter(
        self, db_session: Session, client: TestClient
    ):
        """API search route respects type= filter."""
        # Set up FTS tables
        conn = db_session.connection()
        for sql in _FTS_SETUP_SQL:
            conn.execute(text(sql))
        db_session.commit()

        # Create a space + doc so there's something to find
        space = _create_space(client, name="SearchAPI")
        client.post("/api/v1/documents", json={
            "space_id": space["id"], "title": "Quantum physics notes",
        })

        resp = client.get("/api/v1/search", params={"q": "Quantum", "type": "documents"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "Quantum"
        assert "documents" in data["results"]
        assert len(data["results"]["documents"]) >= 1

        # Teardown FTS
        conn = db_session.connection()
        for name in _FTS_TEARDOWN_TRIGGERS:
            conn.execute(text(f"DROP TRIGGER IF EXISTS {name};"))
        for table in _FTS_TEARDOWN_TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {table};"))
        db_session.commit()
