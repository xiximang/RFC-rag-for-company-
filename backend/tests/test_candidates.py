"""Step 1.1 tests: candidate exposure (read-only) in /v1/chat response.

Verifies the five-level permission inheritance at the candidate layer:
- L5 downgrade: filtered candidates carry placeholder content, never original.
- candidate chunk_id set == sources chunk_id set.
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import chat as chat_api


FAKE_USER = SimpleNamespace(
    id=uuid.uuid4(),
    username="admin",
    email="alice@example.com",
    display_name="Alice",
    department="Engineering",
    security_level="L0",
    status="active",
    is_active=True,
)
KB_ID = uuid.uuid4()
CONVERSATION_ID = uuid.uuid4()
MESSAGE_ID = uuid.uuid4()


def _make_conversation(**overrides):
    now = datetime.now(timezone.utc)
    defaults = {
        "id": CONVERSATION_ID,
        "user_id": FAKE_USER.id,
        "title": "Test",
        "kb_ids": [str(KB_ID)],
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_message(**overrides):
    now = datetime.now(timezone.utc)
    defaults = {
        "id": MESSAGE_ID,
        "conversation_id": CONVERSATION_ID,
        "role": "assistant",
        "content": "hello",
        "sources": [],
        "feedback_rating": None,
        "feedback_comment": None,
        "created_at": now,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture
def api_client():
    app = FastAPI()
    app.include_router(chat_api.router, prefix="/api/v1")
    app.dependency_overrides[chat_api.get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[chat_api.get_db] = lambda: AsyncMock()
    return TestClient(app)


def _patched_chat_mocks():
    """Return a dict of mocks for a full chat flow with one normal + one filtered chunk."""
    retrieval_chunks = [
        {
            "chunk_id": "chunk-normal",
            "doc_id": "doc-1",
            "content": "正常公开内容",
            "modality": "text",
            "score": 0.9,
            "rerank_score": 0.92,
            "max_keyword_level": "L0",
            "filtered": False,
        },
        {
            "chunk_id": "chunk-secret",
            "doc_id": "doc-1",
            "content": "[内容涉及更高敏感级别，已过滤]",
            "modality": "text",
            "score": 0.5,
            "rerank_score": 0.55,
            "max_keyword_level": "L3",
            "filtered": True,
        },
    ]
    return retrieval_chunks


@patch("app.api.v1.chat.conversation_service")
@patch("app.api.v1.chat.security_gateway")
@patch("app.api.v1.chat.generation_service")
@patch("app.api.v1.chat.retrieval_service")
def test_candidates_present_and_filtered(
    mock_retrieval, mock_gen_service, mock_security, mock_conv_service, api_client
):
    """candidates field exists; filtered chunk carries placeholder content."""
    chunks = _patched_chat_mocks()
    mock_conv_service.get_conversation = AsyncMock(return_value=_make_conversation())
    mock_conv_service.build_history_messages = AsyncMock(return_value=[])
    mock_conv_service.add_message = AsyncMock(return_value=_make_message())
    mock_retrieval.search = AsyncMock(return_value=chunks)
    mock_security.detect_prompt_injection.return_value = False
    mock_security._fast_level_check = AsyncMock(return_value=None)
    mock_security.decide_api_strategy = AsyncMock(
        return_value={"strategy": "direct_api", "max_level": 0, "reason": "ok"}
    )
    mock_gen_service.generate_answer = AsyncMock(
        return_value={
            "answer": "ans",
            "intercepted": False,
            "sources": [
                {
                    "doc_id": c["doc_id"],
                    "chunk_id": c["chunk_id"],
                    "content": c["content"],
                    "score": c["rerank_score"],
                    "modality": c["modality"],
                }
                for c in chunks
            ],
        }
    )

    resp = api_client.post(
        "/api/v1/chat/",
        json={
            "query": "q",
            "kb_ids": [str(KB_ID)],
            "conversation_id": str(CONVERSATION_ID),
        },
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("candidates") is not None
    assert len(data["candidates"]) == 2

    by_cid = {c["chunk_id"]: c for c in data["candidates"]}
    # rank starts at 1
    assert {c["rank"] for c in data["candidates"]} == {1, 2}
    # filtered chunk: L5 downgrade reflected
    secret = by_cid["chunk-secret"]
    assert secret["filtered"] is True
    assert secret["max_keyword_level"] == "L3"
    assert secret["content"] == "[内容涉及更高敏感级别，已过滤]"
    # normal chunk not filtered
    normal = by_cid["chunk-normal"]
    assert normal["filtered"] is False
    assert normal["content"] == "正常公开内容"


@patch("app.api.v1.chat.conversation_service")
@patch("app.api.v1.chat.security_gateway")
@patch("app.api.v1.chat.generation_service")
@patch("app.api.v1.chat.retrieval_service")
def test_candidate_chunk_set_equals_sources(
    mock_retrieval, mock_gen_service, mock_security, mock_conv_service, api_client
):
    """candidate chunk_id set must equal sources chunk_id set."""
    chunks = _patched_chat_mocks()
    mock_conv_service.get_conversation = AsyncMock(return_value=_make_conversation())
    mock_conv_service.build_history_messages = AsyncMock(return_value=[])
    mock_conv_service.add_message = AsyncMock(return_value=_make_message())
    mock_retrieval.search = AsyncMock(return_value=chunks)
    mock_security.detect_prompt_injection.return_value = False
    mock_security._fast_level_check = AsyncMock(return_value=None)
    mock_security.decide_api_strategy = AsyncMock(
        return_value={"strategy": "direct_api", "max_level": 0, "reason": "ok"}
    )
    mock_gen_service.generate_answer = AsyncMock(
        return_value={
            "answer": "ans",
            "intercepted": False,
            "sources": [
                {
                    "doc_id": c["doc_id"],
                    "chunk_id": c["chunk_id"],
                    "content": c["content"],
                    "score": c["rerank_score"],
                    "modality": c["modality"],
                }
                for c in chunks
            ],
        }
    )

    resp = api_client.post(
        "/api/v1/chat/",
        json={"query": "q", "kb_ids": [str(KB_ID)]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    src_cids = {s["chunk_id"] for s in data["sources"]}
    cand_cids = {c["chunk_id"] for c in data["candidates"]}
    assert src_cids == cand_cids


# ------------------------------------------------------------------
# Step 1.2: candidate persistence
# ------------------------------------------------------------------
@patch("app.api.v1.chat.conversation_service")
@patch("app.api.v1.chat.security_gateway")
@patch("app.api.v1.chat.generation_service")
@patch("app.api.v1.chat.retrieval_service")
def test_assistant_message_persisted_with_candidates(
    mock_retrieval, mock_gen_service, mock_security, mock_conv_service, api_client
):
    """非流式 chat 落库时 assistant 消息携带 candidates（降级后值）。"""
    chunks = _patched_chat_mocks()
    mock_conv_service.get_conversation = AsyncMock(return_value=_make_conversation())
    mock_conv_service.build_history_messages = AsyncMock(return_value=[])
    mock_conv_service.add_message = AsyncMock(return_value=_make_message())
    mock_retrieval.search = AsyncMock(return_value=chunks)
    mock_security.detect_prompt_injection.return_value = False
    mock_security._fast_level_check = AsyncMock(return_value=None)
    mock_security.decide_api_strategy = AsyncMock(
        return_value={"strategy": "direct_api", "max_level": 0, "reason": "ok"}
    )
    mock_gen_service.generate_answer = AsyncMock(
        return_value={
            "answer": "ans",
            "intercepted": False,
            "sources": [
                {
                    "doc_id": c["doc_id"],
                    "chunk_id": c["chunk_id"],
                    "content": c["content"],
                    "score": c["rerank_score"],
                    "modality": c["modality"],
                }
                for c in chunks
            ],
        }
    )

    resp = api_client.post(
        "/api/v1/chat/",
        json={
            "query": "q",
            "kb_ids": [str(KB_ID)],
            "conversation_id": str(CONVERSATION_ID),
        },
    )
    assert resp.status_code == 200, resp.text

    # add_message 第二次调用是 assistant，应带 candidates
    calls = mock_conv_service.add_message.await_args_list
    assert len(calls) == 2
    assistant_call = calls[1]
    assert assistant_call.kwargs["role"] == "assistant"
    persisted_cands = assistant_call.kwargs.get("candidates")
    assert persisted_cands is not None
    assert len(persisted_cands) == 2
    # 降级值原样落库
    secret = next(c for c in persisted_cands if c["chunk_id"] == "chunk-secret")
    assert secret["filtered"] is True
    assert secret["content"] == "[内容涉及更高敏感级别，已过滤]"


def _make_message_with_candidates():
    msg = _make_message()
    msg.candidates = [
        {
            "rank": 1,
            "chunk_id": "chunk-secret",
            "doc_id": "doc-1",
            "content": "[内容涉及更高敏感级别，已过滤]",
            "rerank_score": 0.55,
            "max_keyword_level": "L3",
            "filtered": True,
        }
    ]
    msg.candidate_feedback = None
    return msg


@patch("app.api.v1.chat.conversation_service")
def test_get_messages_returns_candidates(mock_conv_service, api_client):
    """历史回看：get_messages 返回的 assistant 消息带 candidates（降级值）。"""
    mock_conv_service.get_conversation = AsyncMock(return_value=_make_conversation())
    mock_conv_service.get_messages = AsyncMock(
        return_value=[_make_message_with_candidates()]
    )

    resp = api_client.get(f"/api/v1/chat/conversations/{CONVERSATION_ID}/messages")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 1
    cands = data[0].get("candidates")
    assert cands is not None
    assert len(cands) == 1
    assert cands[0]["filtered"] is True
    assert cands[0]["content"] == "[内容涉及更高敏感级别，已过滤]"
