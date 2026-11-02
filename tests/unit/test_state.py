import pytest

from testagent.core.errors import AppError
from testagent.services.state import MACHINES, allowed, transition


def test_legal_transitions():
    assert transition("version", "planning", "requirements_frozen") == "requirements_frozen"
    assert transition("defect", "closed", "open") == "open"
    assert "running" in allowed("task", "ready")


def test_illegal_transition_rejected():
    with pytest.raises(AppError) as exc:
        transition("version", "closed", "planning")
    assert exc.value.code == "INVALID_TRANSITION"
    with pytest.raises(AppError) as exc:
        transition("task_run", "passed", "running")
    assert exc.value.code == "INVALID_TRANSITION"


def test_unknown_state_is_validation_error():
    with pytest.raises(AppError) as exc:
        transition("version", "planning", "bogus")
    assert exc.value.code == "VALIDATION"


def test_unfreeze_requires_reason():
    with pytest.raises(AppError) as exc:
        transition("version", "requirements_frozen", "planning")
    assert exc.value.field_errors[0]["field"] == "reason"
    assert transition("version", "requirements_frozen", "planning", reason="Requirement change") == "planning"


def test_every_target_is_a_known_state():
    for machine, table in MACHINES.items():
        for targets in table.values():
            assert targets <= set(table), machine
