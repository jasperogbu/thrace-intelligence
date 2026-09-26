#!/usr/bin/env python3
"""Offline checks for quota handling in the model-rotation layer.

The free tier allows 20 requests per model per day. When that daily allowance is
gone, retrying cannot help, so the run must fail immediately with a message the
user can act on instead of sleeping through the whole model pool first (that
turned a 1-second failure into a 136-second one).

Makes no provider calls, and pins the model pool so it does not depend on .env.
Exits non-zero if any check fails.
"""
import os
import sys

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
sys.path.insert(0, os.path.normpath(BACKEND))

import agents  # noqa: E402

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {label}{('  — ' + detail) if detail else ''}")
    if not cond:
        FAILURES.append(label)


# Shaped like the real provider payload, including the daily-quota id.
DAILY_QUOTA = RuntimeError(
    '429 {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", '
    '"message": "You exceeded your current quota", "details": [{'
    '"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}}'
)
BURST_LIMIT = RuntimeError("503 The model is experiencing high demand. Please try again.")


POOL = ["model-a", "model-b", "model-c"]
agents._model_pool = lambda: list(POOL)


def reset() -> None:
    agents._quota_marks.clear()


# --- classification --------------------------------------------------------
check("daily quota is recognised", agents._is_daily_quota_error(DAILY_QUOTA))
check("a burst limit is not classified as daily", not agents._is_daily_quota_error(BURST_LIMIT))

# --- a burst limit still rotates ------------------------------------------
reset()
check("a burst limit rotates to the next model", agents._rotate_on(POOL[0], BURST_LIMIT, 1, 10) is True)
check(
    "one benched model does not look like exhaustion",
    not agents._all_models_benched(),
)

# --- a daily error rotates while other models still have allowance ---------
reset()
check(
    "a daily error rotates while other models may still have allowance",
    agents._rotate_on(POOL[0], DAILY_QUOTA, 1, 10) is True,
)

# --- once every model is out of daily allowance, fail fast -----------------
reset()
raised: Exception | None = None
attempts = 0
for model in POOL:
    attempts += 1
    try:
        agents._rotate_on(model, DAILY_QUOTA, 1, 10)
    except RuntimeError as exc:
        raised = exc
        break

check("fails fast once every model is out of daily allowance", raised is not None)
check(
    "it fails after one pass over the pool, not after the full retry budget",
    attempts <= len(POOL),
    f"{attempts} attempts for a pool of {len(POOL)}",
)
message = str(raised)
check("the message names the daily ceiling", "Daily free-tier ceiling" in message)
check("the message names the pooled models", POOL[0] in message)
check("the message suggests a fix", "LLM_API_KEY" in message)
check("the message explains instant mode", "instant mode" in message)

# The layers above retry anything matching a transient marker, so the fast-fail
# message must not match one or it would be retried anyway.
hits = [m for m in agents._TRANSIENT_MARKERS if m in message.lower()]
check("the fast-fail message is not itself treated as transient", not hits, str(hits))

# --- a partially benched pool is not "exhausted" ---------------------------
reset()
agents._mark_model_exhausted(POOL[0], 30)
check(
    "a partially benched pool is not considered exhausted",
    not agents._all_models_benched(),
)

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("all checks passed")
