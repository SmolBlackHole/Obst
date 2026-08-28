from __future__ import annotations

from pathlib import Path


def test_concrete_extensions_do_not_access_private_resource_budgets() -> None:
    extension_root = Path(__file__).parents[1] / "src" / "obst_defaults"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in extension_root.rglob("*.py")
    )

    assert "ResourceBudget" not in source
    assert "._operation_budget" not in source
