"""Independent examples catch threshold, authorization and duplicate side-effect bugs.

TC-091/092/093/104: this tests the sample, not platform-wide acceptance.
"""

import importlib

import pytest


def service(tmp_path):
    try:
        module = importlib.import_module("examples.procurement.service")
    except ModuleNotFoundError:
        pytest.fail("Procurement sample service has not been implemented")
    return module.ProcurementService(tmp_path / "sample.db")


@pytest.mark.parametrize("amount,want", [(4999999, False), (5000000, True), (5000001, True)])
def test_review_threshold_in_minor_units(tmp_path, amount, want):
    sample = service(tmp_path)
    order = sample.create_order(amount, "CNY")
    assert order["approval_required"] is want


@pytest.mark.parametrize("amount,currency", [(None, "CNY"), (5000000, "USD")])
def test_unconfirmed_inputs_do_not_create_a_certain_rule_result(tmp_path, amount, currency):
    sample = service(tmp_path)
    order = sample.create_order(amount, currency)
    assert order["approval_required"] is None
    assert order["state"] == "unknown"
    with pytest.raises(ValueError):
        sample.pay(order["id"], "callback-1")
    assert sample.payments(order["id"]) == []


@pytest.mark.parametrize("reject_first", [False, True])
def test_unapproved_payment_never_reaches_ledger(tmp_path, reject_first):
    sample = service(tmp_path)
    order = sample.create_order(5000000, "CNY")
    if reject_first:
        sample.decide(order["id"], approved=False)
    with pytest.raises(ValueError):
        sample.pay(order["id"], "callback-1")
    assert sample.payments(order["id"]) == []


def test_callback_replay_is_idempotent_across_restart(tmp_path):
    sample = service(tmp_path)
    order = sample.create_order(5000000, "CNY")
    sample.decide(order["id"], approved=True)
    payment = sample.pay(order["id"], "callback-1")
    restarted = service(tmp_path)
    assert restarted.pay(order["id"], "callback-1") == payment
    assert len(restarted.payments(order["id"])) == 1


def test_new_callback_cannot_pay_the_same_order_twice(tmp_path):
    sample = service(tmp_path)
    order = sample.create_order(5000000, "CNY")
    sample.decide(order["id"], approved=True)
    sample.pay(order["id"], "callback-1")
    with pytest.raises(ValueError):
        sample.pay(order["id"], "callback-2")
    assert len(sample.payments(order["id"])) == 1


def test_rejected_order_cannot_be_approved_afterwards(tmp_path):
    sample = service(tmp_path)
    order = sample.create_order(5000000, "CNY")
    sample.decide(order["id"], approved=False)
    with pytest.raises(ValueError):
        sample.decide(order["id"], approved=True)


def test_below_threshold_is_auto_approved_and_paid_once(tmp_path):
    # small CNY orders are approved automatically (was "policy_unknown")
    sample = service(tmp_path)
    order = sample.create_order(4999999, "CNY")
    assert (order["state"], order["approval_required"]) == ("approved", False)
    sample.pay(order["id"], "callback-1")
    with pytest.raises(ValueError):
        sample.pay(order["id"], "callback-2")
    assert len(sample.payments(order["id"])) == 1


@pytest.mark.parametrize("amount", [-1, True, 50000.5, "5000000"])
def test_invalid_money_is_rejected(tmp_path, amount):
    sample = service(tmp_path)
    with pytest.raises(ValueError):
        sample.create_order(amount, "CNY")
