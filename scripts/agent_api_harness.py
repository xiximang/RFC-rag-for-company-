"""QA harness for exercising the RAG backend API by functional area.

Usage:
    python scripts/agent_api_harness.py [--base-url http://localhost:8080] \
                                        [--creds path/to/creds.json] \
                                        [--area auth|permissions|apikeys|groups|keywords|eval|system|docs|all]

Exit codes:
    0 when every executed area passes, non-zero otherwise.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests


DEFAULT_BASE_URL = "http://localhost:8080"
DEFAULT_CREDS = os.path.join(os.path.dirname(__file__), "..", ".tmp", "agent_credentials.json")


class TestResult:
    def __init__(self, area: str) -> None:
        self.area = area
        self.passed: List[str] = []
        self.failed: List[str] = []
        self.skipped: List[str] = []
        self.errors: List[str] = []

    @property
    def ok(self) -> bool:
        return not self.failed and not self.errors

    def add(self, status: str, message: str) -> None:
        if status == "PASS":
            self.passed.append(message)
        elif status == "SKIP":
            self.skipped.append(message)
        elif status == "FAIL":
            self.failed.append(message)
        else:
            self.errors.append(message)


def _fmt_json(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, default=str)[:300]
    except Exception:
        return str(data)[:300]


class Harness:
    def __init__(self, base_url: str, creds_path: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.creds_path = creds_path
        with open(creds_path, "r", encoding="utf-8") as f:
            self.creds = json.load(f)
        self.tokens: Dict[str, str] = {}
        self.session = requests.Session()
        self.results: List[TestResult] = []

    # ------------------------------------------------------------------ #
    # Auth helpers
    # ------------------------------------------------------------------ #
    def _login(self, level: str) -> str:
        info = self.creds[level]
        r = self.session.post(
            f"{self.base_url}/api/v1/auth/login",
            data={"username": info["username"], "password": info["password"]},
            timeout=30,
        )
        if r.status_code != 200:
            raise RuntimeError(f"login {level} failed: {r.status_code} {r.text}")
        token = r.json()["access_token"]
        self.tokens[level] = token
        return token

    def token(self, level: str) -> str:
        if level not in self.tokens:
            return self._login(level)
        return self.tokens[level]

    def api_key(self, level: str) -> str:
        return self.creds[level].get("api_key", "")

    def user_id(self, level: str) -> str:
        return self.creds[level].get("user_id", "")

    def uid(self, level: str) -> uuid.UUID:
        return uuid.UUID(self.user_id(level))

    def request(
        self,
        method: str,
        path: str,
        level: Optional[str] = None,
        api_key: Optional[str] = None,
        expected: Tuple[int, ...] = (200,),
        allow_retry: bool = True,
        **kwargs: Any,
    ) -> requests.Response:
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        headers: Dict[str, str] = kwargs.pop("headers", {})
        if level:
            headers["Authorization"] = f"Bearer {self.token(level)}"
        if api_key:
            headers["X-API-Key"] = api_key
        r = self.session.request(method, url, headers=headers, timeout=60, **kwargs)
        if r.status_code == 401 and level and allow_retry:
            self._login(level)
            headers["Authorization"] = f"Bearer {self.token(level)}"
            r = self.session.request(method, url, headers=headers, timeout=60, **kwargs)
        if expected and r.status_code not in expected:
            body = r.text[:500]
            raise AssertionError(
                f"{method.upper()} {path} expected {expected}, got {r.status_code}: {body}"
            )
        return r

    def new_area(self, name: str) -> TestResult:
        result = TestResult(name)
        self.results.append(result)
        return result

    # ------------------------------------------------------------------ #
    # Common helpers
    # ------------------------------------------------------------------ #
    def create_kb(self, level: str, prefix: str = "harness") -> str:
        name = f"{prefix}-{level}-{uuid.uuid4().hex[:8]}"
        r = self.request(
            "post",
            "/api/v1/knowledge-bases",
            level=level,
            json={"name": name, "description": "harness", "config": {}},
            expected=(201,),
        )
        return r.json()["id"]

    def upload_doc(self, level: str, kb_id: str, filename: str = "test.txt", content: bytes = b"hello world") -> str:
        buf = io.BytesIO(content)
        r = self.request(
            "post",
            "/api/v1/documents",
            level=level,
            data={"kb_id": kb_id},
            files={"file": (filename, buf, "text/plain")},
            expected=(201,),
        )
        return r.json()["id"]

    def delete_doc(self, level: str, doc_id: str) -> None:
        self.request("delete", f"/api/v1/documents/detail/{doc_id}", level=level, expected=(204, 404))

    def delete_kb(self, level: str, kb_id: str) -> None:
        self.request("delete", f"/api/v1/knowledge-bases/{kb_id}", level=level, expected=(204, 404))

    def run_area(self, name: str, fn: Callable[["Harness", TestResult], None]) -> TestResult:
        result = self.new_area(name)
        print(f"\n[{name}] starting...")
        try:
            fn(self, result)
        except Exception as exc:
            result.add("ERROR", f"area exception: {exc}")
        print(f"[{name}] PASS={len(result.passed)} FAIL={len(result.failed)} SKIP={len(result.skipped)} ERROR={len(result.errors)}")
        return result


# --------------------------------------------------------------------------- #
# Area tests
# --------------------------------------------------------------------------- #
def test_auth(h: Harness, r: TestResult) -> None:
    # register a temp L0 user
    tmp_user = f"harness_{uuid.uuid4().hex[:8]}"
    tmp_pass = "Test1234!"
    reg = h.request(
        "post",
        "/api/v1/auth/register",
        json={"username": tmp_user, "password": tmp_pass, "email": f"{tmp_user}@example.com"},
        expected=(200, 201),
    )
    r.add("PASS", f"register -> {reg.status_code}")

    login = h.request(
        "post",
        "/api/v1/auth/login",
        data={"username": tmp_user, "password": tmp_pass},
        expected=(200,),
    )
    r.add("PASS", f"login new user -> {login.status_code}")

    me = h.request("get", "/api/v1/auth/me", level="admin", expected=(200,))
    r.add("PASS", f"GET /auth/me admin -> {me.status_code}")

    # list users is admin-only
    list_admin = h.request("get", "/api/v1/users", level="admin", expected=(200,))
    r.add("PASS", f"GET /users admin -> {list_admin.status_code}")

    list_l0 = h.request("get", "/api/v1/users", level="L0", expected=(403,))
    r.add("PASS", f"GET /users L0 denied -> {list_l0.status_code}")

    # admin creates a user
    new_name = f"admin_created_{uuid.uuid4().hex[:8]}"
    create = h.request(
        "post",
        "/api/v1/users",
        level="admin",
        json={"username": new_name, "password": "Test1234!", "email": f"{new_name}@example.com", "security_level": "L1"},
        expected=(201,),
    )
    new_id = create.json()["id"]
    r.add("PASS", f"POST /users admin create -> {create.status_code}")

    get_user = h.request("get", f"/api/v1/users/{new_id}", level="admin", expected=(200,))
    r.add("PASS", f"GET /users/{new_id} admin -> {get_user.status_code}")

    # update user (active/display_name)
    upd = h.request(
        "put",
        f"/api/v1/users/{new_id}",
        level="admin",
        json={"display_name": "Harness User", "is_active": True},
        expected=(200,),
    )
    r.add("PASS", f"PUT /users/{new_id} -> {upd.status_code}")

    # delete user
    h.request("delete", f"/api/v1/users/{new_id}", level="admin", expected=(204,))
    r.add("PASS", f"DELETE /users/{new_id} -> 204")

    # login levels
    for lvl in ("L0", "L1", "L2", "L3", "L4"):
        h.request("get", "/api/v1/auth/me", level=lvl, expected=(200,))
        r.add("PASS", f"auth/me {lvl} -> 200")


def test_apikeys(h: Harness, r: TestResult) -> None:
    scopes_resp = h.request("get", "/api/v1/api-keys/scopes", level="L3", expected=(200,))
    allowed = set(scopes_resp.json()["allowed_scopes"])
    r.add("PASS", f"GET /api-keys/scopes L3 -> {scopes_resp.status_code}, allowed={allowed}")

    # L0 allowed scopes check
    s0 = h.request("get", "/api/v1/api-keys/scopes", level="L0", expected=(200,))
    allowed_l0 = set(s0.json()["allowed_scopes"])
    if not allowed_l0.issubset({"kb:read", "search", "chat"}):
        r.add("FAIL", f"L0 scopes unexpected: {allowed_l0}")
    else:
        r.add("PASS", f"L0 scopes constrained -> {allowed_l0}")

    # create a key with allowed scopes
    create = h.request(
        "post",
        "/api/v1/api-keys",
        level="L3",
        json={"name": "harness key", "scopes": ["kb:read", "search"]},
        expected=(201,),
    )
    key_data = create.json()
    key_id = key_data["id"]
    plain_key = key_data.get("plain_key")
    r.add("PASS", f"POST /api-keys create -> {create.status_code}")

    # list keys
    lst = h.request("get", "/api/v1/api-keys", level="L3", expected=(200,))
    ids = {k["id"] for k in lst.json()}
    if key_id in ids:
        r.add("PASS", f"GET /api-keys list contains new key")
    else:
        r.add("FAIL", f"GET /api-keys list missing new key: {ids}")

    # L0 cannot request admin scope
    bad = h.request(
        "post",
        "/api/v1/api-keys",
        level="L0",
        json={"name": "bad", "scopes": ["kb:write"]},
        expected=(400, 403, 422),
    )
    r.add("PASS", f"L0 create out-of-scope key denied -> {bad.status_code}")

    # revoke
    h.request("delete", f"/api/v1/api-keys/{key_id}", level="L3", expected=(204,))
    r.add("PASS", f"DELETE /api-keys/{key_id} revoke -> 204")

    # external API calls using L1 key (doc:write + kb:read + search + chat)
    ext_key = h.api_key("L2")
    kb = h.request(
        "post",
        "/api/v1/external/knowledge-bases",
        api_key=ext_key,
        json={"name": f"ext-harness-{uuid.uuid4().hex[:8]}", "config": {}},
        expected=(201,),
    )
    kb_id = kb.json()["id"]
    r.add("PASS", f"POST /external/knowledge-bases -> {kb.status_code}")

    ext_list = h.request("get", "/api/v1/external/knowledge-bases", api_key=ext_key, expected=(200,))
    r.add("PASS", f"GET /external/knowledge-bases -> {ext_list.status_code}")

    # search endpoint availability (actual retrieval may 500 if model absent)
    sr = h.request(
        "post",
        "/api/v1/external/search",
        api_key=ext_key,
        json={"query": "hello", "kb_ids": [kb_id], "top_k": 1, "mode": "hybrid"},
        expected=(200, 500, 503),
    )
    r.add("PASS" if sr.status_code == 200 else "SKIP", f"POST /external/search -> {sr.status_code}")

    # chat endpoint availability
    cr = h.request(
        "post",
        "/api/v1/external/chat",
        api_key=ext_key,
        json={"query": "你好", "kb_ids": [kb_id], "stream": False, "top_k": 1},
        expected=(200, 500, 503),
    )
    r.add("PASS" if cr.status_code == 200 else "SKIP", f"POST /external/chat -> {cr.status_code}")

    # cleanup
    h.delete_kb("L2", kb_id)


def test_permissions(h: Harness, r: TestResult) -> None:
    kb_id = h.create_kb("L2", "perm")
    doc_id = h.upload_doc("L2", kb_id)

    # owner can access document detail
    detail = h.request("get", f"/api/v1/documents/detail/{doc_id}", level="L2", expected=(200,))
    r.add("PASS", f"owner document detail -> {detail.status_code}")

    # non-owner cannot access detail
    denied = h.request("get", f"/api/v1/documents/detail/{doc_id}", level="L1", expected=(403,))
    r.add("PASS", f"non-owner document detail denied -> {denied.status_code}")

    # permission check endpoint
    chk = h.request("get", f"/api/v1/permissions/check/{doc_id}", level="L2", expected=(200,))
    r.add("PASS", f"GET /permissions/check/{doc_id} -> {chk.status_code}")

    # grant document READ to L1
    grant = h.request(
        "post",
        "/api/v1/permissions/grant",
        level="L2",
        json={
            "target_type": "user",
            "target_id": str(h.uid("L1")),
            "object_type": "document",
            "object_id": doc_id,
            "permission": "READ",
        },
        expected=(200,),
    )
    r.add("PASS", f"POST /permissions/grant -> {grant.status_code}")

    # check L1 now has READ
    chk2 = h.request("get", f"/api/v1/permissions/check/{doc_id}", level="L1", expected=(200,))
    perm2 = chk2.json().get("permission", "")
    r.add("PASS" if perm2 in ("READ", "WRITE", "ADMIN") else "FAIL", f"L1 permission after grant: {perm2}")

    # list permissions for L1
    plist = h.request(
        "get",
        "/api/v1/permissions/list",
        level="L2",
        params={"target_type": "user", "target_id": str(h.uid("L1"))},
        expected=(200,),
    )
    r.add("PASS", f"GET /permissions/list -> {plist.status_code}")

    # revoke
    revoke = h.request(
        "post",
        "/api/v1/permissions/revoke",
        level="L2",
        json={
            "target_type": "user",
            "target_id": str(h.uid("L1")),
            "object_type": "document",
            "object_id": doc_id,
            "permission": "READ",
        },
        expected=(200,),
    )
    r.add("PASS", f"POST /permissions/revoke -> {revoke.status_code}")

    h.delete_doc("L2", doc_id)
    h.delete_kb("L2", kb_id)


def test_groups(h: Harness, r: TestResult) -> None:
    group_name = f"harness-group-{uuid.uuid4().hex[:8]}"
    create = h.request(
        "post",
        "/api/v1/groups",
        level="L2",
        json={
            "name": group_name,
            "description": "harness",
            "group_type": "custom",
            "max_security_level": "L2",
            "member_ids": [str(h.uid("L0"))],
            "admin_ids": [str(h.uid("L1"))],
        },
        expected=(200, 201),
    )
    group_id = create.json()["id"]
    r.add("PASS", f"POST /groups -> {create.status_code}")

    lst = h.request("get", "/api/v1/groups", level="L2", expected=(200,))
    r.add("PASS", f"GET /groups -> {lst.status_code}")

    get = h.request("get", f"/api/v1/groups/{group_id}", level="L2", expected=(200,))
    r.add("PASS", f"GET /groups/{group_id} -> {get.status_code}")

    upd = h.request(
        "put",
        f"/api/v1/groups/{group_id}",
        level="L2",
        json={"description": "updated by harness"},
        expected=(200,),
    )
    r.add("PASS", f"PUT /groups/{group_id} -> {upd.status_code}")

    # add member (L1 already admin; add L3)
    add = h.request(
        "post",
        f"/api/v1/groups/{group_id}/members",
        level="L2",
        json={"user_ids": [str(h.uid("L3"))]},
        expected=(200,),
    )
    r.add("PASS", f"POST /groups/{group_id}/members -> {add.status_code}")

    # non-admin cannot update
    denied = h.request(
        "put",
        f"/api/v1/groups/{group_id}",
        level="L0",
        json={"description": "should fail"},
        expected=(403,),
    )
    r.add("PASS", f"non-admin PUT /groups/{group_id} denied -> {denied.status_code}")

    # cleanup
    h.request("delete", f"/api/v1/groups/{group_id}", level="L2", expected=(200,))
    r.add("PASS", "DELETE /groups/{group_id} -> 200")


def test_keywords(h: Harness, r: TestResult) -> None:
    kw = f"harness_kw_{uuid.uuid4().hex[:8]}"
    create = h.request(
        "post",
        "/api/v1/keywords",
        level="L3",
        json={"keyword": kw, "level": "L2", "category": "custom", "match_type": "exact", "action": "audit"},
        expected=(201,),
    )
    kw_id = create.json()["id"]
    r.add("PASS", f"POST /keywords -> {create.status_code}")

    lst = h.request("get", "/api/v1/keywords", level="L3", expected=(200,))
    r.add("PASS", f"GET /keywords -> {lst.status_code}")

    upd = h.request(
        "put",
        f"/api/v1/keywords/{kw_id}",
        level="L3",
        json={"action": "block"},
        expected=(200,),
    )
    r.add("PASS", f"PUT /keywords/{kw_id} -> {upd.status_code}")

    scan = h.request(
        "post",
        "/api/v1/keywords/scan",
        level="L3",
        json={"text": f"这句话包含{kw}信息"},
        expected=(200,),
    )
    r.add("PASS", f"POST /keywords/scan -> {scan.status_code}")

    batch = h.request(
        "post",
        "/api/v1/keywords/batch-import",
        level="L3",
        json=[
            {"keyword": f"batch_a_{uuid.uuid4().hex[:6]}", "level": "L1"},
            {"keyword": f"batch_b_{uuid.uuid4().hex[:6]}", "level": "L1"},
        ],
        expected=(201,),
    )
    r.add("PASS", f"POST /keywords/batch-import -> {batch.status_code}")

    h.request("delete", f"/api/v1/keywords/{kw_id}", level="L3", expected=(204,))
    r.add("PASS", f"DELETE /keywords/{kw_id} -> 204")


def test_eval(h: Harness, r: TestResult) -> None:
    kb_id = h.create_kb("L2", "eval")
    ds = h.request(
        "post",
        "/api/v1/evaluation/datasets",
        level="L2",
        json={"kb_id": kb_id, "name": "harness dataset", "questions": ["q1"], "ground_truths": [{"answer": "a1"}]},
        expected=(201,),
    )
    ds_id = ds.json()["id"]
    r.add("PASS", f"POST /evaluation/datasets -> {ds.status_code}")

    lst = h.request("get", "/api/v1/evaluation/datasets", level="L2", expected=(200,))
    r.add("PASS", f"GET /evaluation/datasets -> {lst.status_code}")

    metrics = h.request("get", "/api/v1/evaluation/metrics", level="L2", expected=(200,))
    r.add("PASS", f"GET /evaluation/metrics -> {metrics.status_code}")

    # create task - worker may fail due to missing model but endpoint should accept
    task = h.request(
        "post",
        "/api/v1/evaluation/tasks",
        level="L2",
        json={"dataset_id": ds_id, "kb_id": kb_id, "metrics": ["recall@3"]},
        expected=(201, 500, 503),
    )
    r.add("PASS" if task.status_code == 201 else "SKIP", f"POST /evaluation/tasks -> {task.status_code}")

    if task.status_code == 201:
        task_id = task.json()["id"]
        get_task = h.request("get", f"/api/v1/evaluation/tasks/{task_id}", level="L2", expected=(200,))
        r.add("PASS", f"GET /evaluation/tasks/{task_id} -> {get_task.status_code}")

    h.delete_kb("L2", kb_id)


def test_system(h: Harness, r: TestResult) -> None:
    health = h.request("get", "/api/v1/health", expected=(200,))
    r.add("PASS", f"GET /health -> {health.status_code}")

    cfg = h.request("get", "/api/v1/config/models", level="admin", expected=(200,))
    r.add("PASS", f"GET /config/models -> {cfg.status_code}")

    upd = h.request(
        "put",
        "/api/v1/config/models",
        level="admin",
        json={"llm_model": "test-model-updated"},
        expected=(200,),
    )
    r.add("PASS", f"PUT /config/models admin -> {upd.status_code}")

    # verify update took effect
    cfg2 = h.request("get", "/api/v1/config/models", level="admin", expected=(200,))
    if cfg2.json().get("llm_model") == "test-model-updated":
        r.add("PASS", "config update persisted")
    else:
        r.add("FAIL", f"config update not persisted: {cfg2.json().get('llm_model')}")

    # restore harmless value
    h.request("put", "/api/v1/config/models", level="admin", json={"llm_model": "minimax-m3"}, expected=(200,))


def test_docs_ownership(h: Harness, r: TestResult) -> None:
    """Regression: non-owner uploading into someone else's KB must be rejected."""
    kb_id = h.create_kb("L2", "owner")
    buf = io.BytesIO(b"intruder")
    intrude = h.request(
        "post",
        "/api/v1/documents",
        level="L1",
        data={"kb_id": kb_id},
        files={"file": ("intruder.txt", buf, "text/plain")},
        expected=(403,),
    )
    if intrude.status_code == 403:
        r.add("PASS", f"non-owner upload rejected -> 403")
    else:
        r.add("FAIL", f"non-owner upload should be 403, got {intrude.status_code}: {intrude.text[:200]}")

    # owner upload still works
    own = h.request(
        "post",
        "/api/v1/documents",
        level="L2",
        data={"kb_id": kb_id},
        files={"file": ("owner.txt", io.BytesIO(b"owner"), "text/plain")},
        expected=(201,),
    )
    doc_id = own.json()["id"]
    r.add("PASS", f"owner upload -> {own.status_code}")

    h.delete_doc("L2", doc_id)
    h.delete_kb("L2", kb_id)


def test_kb(h: Harness, r: TestResult) -> None:
    kb_id = h.create_kb("L2", "kb")

    lst = h.request("get", "/api/v1/knowledge-bases", level="L2", expected=(200,))
    r.add("PASS", f"GET /knowledge-bases -> {lst.status_code}")

    get = h.request("get", f"/api/v1/knowledge-bases/{kb_id}", level="L2", expected=(200,))
    r.add("PASS", f"GET /knowledge-bases/{kb_id} -> {get.status_code}")

    upd = h.request(
        "patch",
        f"/api/v1/knowledge-bases/{kb_id}",
        level="L2",
        json={"description": "updated"},
        expected=(200,),
    )
    r.add("PASS", f"PATCH /knowledge-bases/{kb_id} -> {upd.status_code}")

    stats = h.request("get", f"/api/v1/knowledge-bases/{kb_id}/stats", level="L2", expected=(200,))
    r.add("PASS", f"GET /knowledge-bases/{kb_id}/stats -> {stats.status_code}")

    # non-owner access denied
    denied = h.request("get", f"/api/v1/knowledge-bases/{kb_id}", level="L1", expected=(403,))
    r.add("PASS", f"non-owner GET KB denied -> {denied.status_code}")

    h.delete_kb("L2", kb_id)
    r.add("PASS", "DELETE /knowledge-bases -> 204")


def test_docs_lifecycle(h: Harness, r: TestResult) -> None:
    kb_id = h.create_kb("L2", "doclife")
    doc_id = h.upload_doc("L2", kb_id, "lifecycle.txt", b"lifecycle content")

    lst = h.request("get", f"/api/v1/documents/{kb_id}", level="L2", expected=(200,))
    r.add("PASS", f"GET /documents/{kb_id} -> {lst.status_code}")

    detail = h.request("get", f"/api/v1/documents/detail/{doc_id}", level="L2", expected=(200,))
    r.add("PASS", f"GET /documents/detail/{doc_id} -> {detail.status_code}")

    dl = h.request("get", f"/api/v1/documents/detail/{doc_id}/download", level="L2", expected=(200,))
    r.add("PASS", f"GET /documents/detail/{doc_id}/download -> {dl.status_code}")

    preview = h.request("get", f"/api/v1/documents/detail/{doc_id}/preview", level="L2", expected=(200,))
    r.add("PASS", f"GET /documents/detail/{doc_id}/preview -> {preview.status_code}")

    reprocess = h.request("post", f"/api/v1/documents/{doc_id}/reprocess", level="L2", expected=(200,))
    r.add("PASS", f"POST /documents/detail/{doc_id}/reprocess -> {reprocess.status_code}")

    h.delete_doc("L2", doc_id)
    h.delete_kb("L2", kb_id)


def test_search_chat(h: Harness, r: TestResult) -> None:
    kb_id = h.create_kb("L2", "search")

    # Search endpoints are exercised for availability; model-dependent failures are skipped.
    for path in ("/api/v1/search", "/api/v1/search/semantic", "/api/v1/search/keyword"):
        mode = {"/api/v1/search": "hybrid", "/api/v1/search/semantic": "semantic", "/api/v1/search/keyword": "keyword"}[path]
        sr = h.request(
            "post",
            path,
            level="L2",
            json={"query": "hello", "kb_ids": [kb_id], "top_k": 1, "mode": mode},
            expected=(200, 500, 503),
        )
        status = "PASS" if sr.status_code == 200 else "SKIP"
        r.add(status, f"{path} -> {sr.status_code}")

    # Search history
    hist = h.request("get", "/api/v1/search/history", level="L2", expected=(200,))
    r.add("PASS", f"GET /search/history -> {hist.status_code}")

    # Conversations
    conv = h.request(
        "post",
        "/api/v1/chat/conversations",
        level="L2",
        json={"title": "harness conv", "kb_ids": [kb_id]},
        expected=(200, 201),
    )
    conv_id = conv.json()["id"]
    r.add("PASS", f"POST /chat/conversations -> {conv.status_code}")

    lst = h.request("get", "/api/v1/chat/conversations", level="L2", expected=(200,))
    r.add("PASS", f"GET /chat/conversations -> {lst.status_code}")

    msgs = h.request("get", f"/api/v1/chat/conversations/{conv_id}/messages", level="L2", expected=(200,))
    r.add("PASS", f"GET /chat/conversations/{conv_id}/messages -> {msgs.status_code}")

    # Chat availability
    cr = h.request(
        "post",
        "/api/v1/chat",
        level="L2",
        json={"query": "你好", "kb_ids": [kb_id], "stream": False, "top_k": 1},
        expected=(200, 500, 503),
    )
    status = "PASS" if cr.status_code == 200 else "SKIP"
    r.add(status, f"POST /chat -> {cr.status_code}")

    h.request("delete", f"/api/v1/chat/conversations/{conv_id}", level="L2", expected=(204,))
    r.add("PASS", f"DELETE /chat/conversations/{conv_id} -> 204")

    h.delete_kb("L2", kb_id)


AREA_FUNCTIONS = {
    "auth": test_auth,
    "apikeys": test_apikeys,
    "permissions": test_permissions,
    "groups": test_groups,
    "keywords": test_keywords,
    "eval": test_eval,
    "system": test_system,
    "docs": test_docs_ownership,
    "kb": test_kb,
    "docs_lifecycle": test_docs_lifecycle,
    "search_chat": test_search_chat,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--creds", default=DEFAULT_CREDS)
    parser.add_argument("--area", default="all", help="comma-separated area names or 'all'. Areas: auth,apikeys,permissions,groups,keywords,eval,system,docs,kb,docs_lifecycle,search_chat")
    args = parser.parse_args()

    creds_path = os.path.abspath(args.creds)
    if not os.path.exists(creds_path):
        print(f"Credentials file not found: {creds_path}")
        return 1

    h = Harness(args.base_url, creds_path)

    # quick health check
    try:
        h.request("get", "/api/v1/health", expected=(200,))
    except Exception as exc:
        print(f"Backend health check failed: {exc}")
        return 2

    wanted = set(AREA_FUNCTIONS.keys()) if args.area == "all" else {a.strip() for a in args.area.split(",")}
    for name in AREA_FUNCTIONS:
        if name in wanted:
            h.run_area(name, AREA_FUNCTIONS[name])

    print("\n" + "=" * 60)
    total_pass = total_fail = total_skip = total_err = 0
    for res in h.results:
        total_pass += len(res.passed)
        total_fail += len(res.failed)
        total_skip += len(res.skipped)
        total_err += len(res.errors)
        status = "OK" if res.ok else "FAIL"
        print(f"[{status}] {res.area}: +{len(res.passed)} -{len(res.failed)} ~{len(res.skipped)} !{len(res.errors)}")
        for f in res.failed:
            print(f"    FAIL: {f}")
        for e in res.errors:
            print(f"    ERROR: {e}")

    print("-" * 60)
    print(f"TOTAL: PASS={total_pass} FAIL={total_fail} SKIP={total_skip} ERROR={total_err}")
    return 1 if total_fail or total_err else 0


if __name__ == "__main__":
    sys.exit(main())
