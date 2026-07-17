import json

from app.llm import get_router
from app.llm.base import LLMResponse, ToolCall
from app.services import code_review

DIFF = """diff --git a/app/x.py b/app/x.py
index 111..222 100644
--- a/app/x.py
+++ b/app/x.py
@@ -1,3 +1,4 @@
+import os
 def f():
-    return 1
+    return os.getenv("X")
diff --git a/package-lock.json b/package-lock.json
index 333..444 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1 +1 @@
-{}
+{"lockfileVersion": 3}
diff --git a/frontend/lib/util.ts b/frontend/lib/util.ts
index 555..666 100644
--- a/frontend/lib/util.ts
+++ b/frontend/lib/util.ts
@@ -1 +1,2 @@
 export const a = 1;
+export const b = 2;
"""


# ---------- diff parsing ----------

def test_split_diff_splits_and_skips_noise():
    files = code_review.split_diff(DIFF)
    paths = [p for p, _ in files]
    assert paths == ["app/x.py", "frontend/lib/util.ts"]  # lockfile skipped
    assert "return os.getenv" in files[0][1]
    assert "export const b" in files[1][1]


def test_skip_patterns():
    assert code_review._skip("node_modules/lodash/index.js")
    assert code_review._skip("frontend/package-lock.json")
    assert code_review._skip("assets/logo.svg")
    assert code_review._skip("bundle.min.js")
    assert not code_review._skip("app/services/scraper.py")


def test_batching_respects_budget():
    files = [("a.py", "x" * 40), ("b.py", "y" * 40), ("c.py", "z" * 40)]
    batches = code_review._batches(files, budget=100)
    assert len(batches) == 2
    assert [p for p, _ in batches[0]] == ["a.py", "b.py"]
    assert [p for p, _ in batches[1]] == ["c.py"]


# ---------- review ----------

class Fake:
    def __init__(self, arguments=None, raise_=False):
        self.arguments = arguments
        self.raise_ = raise_
        self.calls = 0

    async def complete(self, **kw):
        self.calls += 1
        if self.raise_:
            raise RuntimeError("endpoint down")
        return LLMResponse(
            tool_calls=[ToolCall(name="report_findings", arguments=self.arguments)]
        )


def _patch(monkeypatch, provider):
    monkeypatch.setattr(get_router()._registry, "provider_for", lambda spec: provider)
    return provider


async def test_empty_diff_never_calls_llm(temp_db, monkeypatch):
    fake = _patch(monkeypatch, Fake())
    assert await code_review.review_diff("") == []
    # a diff of only noise files is also a no-op
    lock_only = DIFF.split("diff --git a/package-lock.json")[1]
    assert await code_review.review_diff(
        "diff --git a/package-lock.json" + lock_only.split("diff --git")[0]
    ) == []
    assert fake.calls == 0


async def test_review_parses_findings(temp_db, monkeypatch):
    findings_json = json.dumps(
        {
            "findings": [
                {"file": "app/x.py", "severity": "bug", "comment": "getenv may return None"},
            ]
        }
    )
    fake = _patch(monkeypatch, Fake(arguments=findings_json))
    findings = await code_review.review_diff(DIFF)
    assert fake.calls == 1
    assert findings == [
        {"file": "app/x.py", "severity": "bug", "comment": "getenv may return None"}
    ]


async def test_malformed_llm_output_yields_no_findings(temp_db, monkeypatch):
    _patch(monkeypatch, Fake(arguments="{{{not json"))
    assert await code_review.review_diff(DIFF) == []


async def test_provider_failure_never_raises(temp_db, monkeypatch):
    _patch(monkeypatch, Fake(raise_=True))
    assert await code_review.review_diff(DIFF) == []


# ---------- markdown rendering ----------

def test_markdown_groups_by_file_with_severity():
    md = code_review.to_markdown(
        [
            {"file": "a.py", "severity": "bug", "comment": "broken"},
            {"file": "a.py", "severity": "style", "comment": "naming"},
            {"file": "b.ts", "severity": "risk", "comment": "race"},
        ]
    )
    assert md.startswith("## 🤖 SiloLoop code review")
    assert md.index("### `a.py`") < md.index("### `b.ts`")
    assert "**bug** — broken" in md
    assert "**risk** — race" in md


def test_markdown_no_findings_and_cap(monkeypatch):
    md = code_review.to_markdown([])
    assert "No findings" in md

    monkeypatch.setattr(code_review, "MAX_COMMENT_CHARS", 120)
    long = code_review.to_markdown(
        [{"file": "a.py", "severity": "bug", "comment": "x" * 500}]
    )
    assert len(long) <= 120
