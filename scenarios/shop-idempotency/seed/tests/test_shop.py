import pytest

from shop.app import build
from shop.errors import StoreError, UnknownUser


def test_a_new_user_is_known_to_every_service_once_events_run():
    shop = build()
    uid = shop.users.create_user("Ada", "ada@example.org")
    with pytest.raises(UnknownUser):
        shop.orders.create_order(uid, 500)
    shop.bus.run_pending()
    assert shop.orders.create_order(uid, 500).startswith("o")
    assert shop.subscriptions.lists_for(uid) == ["news"]


def test_orders_are_listed_per_user():
    shop = build()
    a = shop.users.create_user("Ada", "ada@example.org")
    b = shop.users.create_user("Bob", "bob@example.org")
    shop.bus.run_pending()
    shop.orders.create_order(a, 100)
    shop.orders.create_order(a, 250)
    shop.orders.create_order(b, 999)
    assert [o["amount_pence"] for o in shop.orders.orders_for(a)] == [100, 250]


def test_amounts_are_whole_pence():
    shop = build()
    uid = shop.users.create_user("Ada", "ada@example.org")
    shop.bus.run_pending()
    with pytest.raises(ValueError):
        shop.orders.create_order(uid, 1.5)


def test_a_failed_handler_is_retried_on_the_next_run():
    shop = build()
    uid = shop.users.create_user("Ada", "ada@example.org")
    shop.subscriptions.store.fail_next_write()
    shop.bus.run_pending()
    assert shop.subscriptions.lists_for(uid) == []
    shop.bus.run_pending()
    assert shop.subscriptions.lists_for(uid) == ["news"]


def test_a_store_write_can_fail():
    shop = build()
    uid = shop.users.create_user("Ada", "ada@example.org")
    shop.bus.run_pending()
    shop.orders.store.fail_next_write()
    with pytest.raises(StoreError):
        shop.orders.create_order(uid, 100)
    assert shop.orders.orders_for(uid) == []


def test_get_user_of_an_unknown_id_raises():
    shop = build()
    with pytest.raises(UnknownUser):
        shop.users.get_user("u-missing")
