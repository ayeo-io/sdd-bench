"""Hidden checks for shop-forget-user. Each test name starts with the id of
the target criterion it checks (see target.md)."""

import ast
import inspect

import pytest

import shop.users
from shop import audit, log
from shop.app import build
from shop.errors import StoreError, UnknownUser
from shop.orders import OrderService
from shop.subscriptions import SubscriptionService


def _customer():
    s = build()
    uid = s.users.create_user("Ada Lovelace", "ada@example.org")
    s.bus.run_pending()
    s.orders.create_order(uid, 500)
    s.orders.create_order(uid, 750)
    s.subscriptions.subscribe(uid, "offers")
    s.bus.run_pending()
    return s, uid


def test_f1_everything_about_the_user_is_gone_once_events_run():
    s, uid = _customer()
    s.users.delete_user(uid)
    s.bus.run_pending()
    with pytest.raises(UnknownUser):
        s.users.get_user(uid)
    assert s.orders.orders_for(uid) == []
    assert s.subscriptions.lists_for(uid) == []


def test_f2_other_users_are_untouched():
    s, uid = _customer()
    other = s.users.create_user("Bob", "bob@example.org")
    s.bus.run_pending()
    s.orders.create_order(other, 100)
    s.users.delete_user(uid)
    s.bus.run_pending()
    assert s.users.get_user(other)["name"] == "Bob"
    assert len(s.orders.orders_for(other)) == 1
    assert s.subscriptions.lists_for(other) == ["news"]


def test_f3_deleting_an_unknown_user_raises():
    s = build()
    with pytest.raises(UnknownUser):
        s.users.delete_user("u-missing")


def test_f4_a_failed_downstream_delete_is_finished_by_a_retry():
    s, uid = _customer()
    s.users.delete_user(uid)
    s.orders.store.fail_next_write()
    s.bus.run_pending()
    assert s.subscriptions.lists_for(uid) == []
    assert s.orders.orders_for(uid) != []
    s.bus.run_pending()
    assert s.orders.orders_for(uid) == []
    assert s.bus.pending_count() == 0


def test_f5_a_duplicate_deletion_message_does_no_harm():
    s, uid = _customer()
    s.users.delete_user(uid)
    s.bus.run_pending()
    s.bus.deliver_again()
    s.bus.run_pending()
    assert s.bus.pending_count() == 0
    assert s.orders.orders_for(uid) == []
    assert s.subscriptions.lists_for(uid) == []


def test_f6_a_new_service_hears_about_the_deletion_without_changing_users():
    s, uid = _customer()
    before = len(s.bus.published)
    s.users.delete_user(uid)
    topics = {m["topic"] for m in s.bus.published[before:]}
    assert topics, "delete_user published no event"
    heard = []
    for topic in topics:
        s.bus.subscribe(topic, heard.append)
    # The new subscriber joined after delete_user published, so send a
    # fresh copy of each event, as a later deletion would.
    for m in list(s.bus.published[before:]):
        s.bus.publish(m["topic"], m["payload"], m["headers"])
    s.bus.run_pending()
    assert any(uid in str(m["payload"]) for m in heard)
    tree = ast.parse(inspect.getsource(shop.users))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not {"shop.orders", "shop.subscriptions"} & imported
    assert not any(isinstance(v, (OrderService, SubscriptionService))
                   for v in vars(s.users).values())


def test_f7_a_late_write_cannot_bring_the_user_back():
    s, uid = _customer()
    s.users.delete_user(uid)
    s.bus.run_pending()
    with pytest.raises(UnknownUser):
        s.orders.create_order(uid, 100)
    with pytest.raises(UnknownUser):
        s.subscriptions.subscribe(uid, "news")


def test_f8_the_deletion_is_audited_without_personal_data():
    s, uid = _customer()
    s.users.delete_user(uid)
    s.bus.run_pending()
    assert any(uid in str(e) for e in audit.ENTRIES)
    text = str(audit.ENTRIES) + str(log.RECORDS) + str(s.bus.published)
    assert "Ada" not in text and "ada@example.org" not in text


def test_f8_every_service_that_held_data_audits_its_deletion():
    s, uid = _customer()
    s.users.delete_user(uid)
    s.bus.run_pending()
    assert len([e for e in audit.ENTRIES if uid in str(e)]) >= 3


def test_f9_a_late_user_created_does_not_bring_the_user_back():
    s = build()
    uid = s.users.create_user("Ada Lovelace", "ada@example.org")
    s.subscriptions.store.fail_next_write()
    s.bus.run_pending()  # orders hears of the user; subscriptions fails, will retry
    s.users.delete_user(uid)
    s.bus.run_pending()
    s.bus.run_pending()
    assert s.subscriptions.lists_for(uid) == []
    assert s.orders.orders_for(uid) == []
    with pytest.raises(UnknownUser):
        s.subscriptions.subscribe(uid, "news")
    assert s.bus.pending_count() == 0


def test_f10_a_failed_delete_in_the_user_service_changes_nothing():
    s, uid = _customer()
    before = len(s.bus.published)
    s.users.store.fail_next_write()
    with pytest.raises(StoreError):
        s.users.delete_user(uid)
    assert s.users.get_user(uid)["name"] == "Ada Lovelace"
    assert len(s.bus.published) == before
    s.bus.run_pending()
    assert len(s.orders.orders_for(uid)) == 2


def test_f11_deleting_twice_raises_the_second_time():
    s, uid = _customer()
    s.users.delete_user(uid)
    with pytest.raises(UnknownUser):
        s.users.delete_user(uid)
