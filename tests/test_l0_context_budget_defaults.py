
### 3. NEW FILE

**Complete path:** `tests/test_l0_context_budget_defaults.py`

```python
from __future__ import annotations

import math

from company_os.context import compile_l0_company_context
from company_os.context.l0_company_context import (
    DEFAULT_MAX_CONTEXT_TOKENS,
    DEFAULT_RESERVED_OUTPUT_TOKENS,
)
from company_os.foundation import FoundationService


def test_l0_default_budget_keeps_at_least_twenty_percent_headroom(tmp_path):
    root = tmp_path / "AI-Dev-Company"
    root.mkdir()

    foundation = FoundationService(root)
    foundation.bootstrap(
        owner_name="Test Owner",
        owner_email="owner@example.com",
        actor="test-suite",
        reason="L0 default budget headroom regression test",
    )

    packet = compile_l0_company_context(foundation)
    budget = packet["budget"]

    assert budget["max_context_tokens"] == DEFAULT_MAX_CONTEXT_TOKENS
    assert budget["reserved_output_tokens"] == DEFAULT_RESERVED_OUTPUT_TOKENS
    assert budget["available_context_tokens"] == (
        DEFAULT_MAX_CONTEXT_TOKENS - DEFAULT_RESERVED_OUTPUT_TOKENS
    )
    assert budget["estimated_context_tokens"] <= budget["available_context_tokens"]

    remaining_headroom = (
        budget["available_context_tokens"]
        - budget["estimated_context_tokens"]
    )
    required_headroom = math.ceil(
        budget["estimated_context_tokens"] * 0.20
    )

    assert remaining_headroom >= required_headroom, (
        "Default L0 budget must preserve at least 20% headroom for controlled "
        "growth of mandatory company context. Increase the approved budget or "
        "review the context contract; do not truncate required policies."
    )
