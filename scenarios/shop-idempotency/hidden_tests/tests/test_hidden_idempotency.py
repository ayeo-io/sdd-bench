import pytest

from shop.app import build
from shop.errors import StoreError


def _shop_with_user():
    shop = build()
    uid = shop.users.create_user("Ada", "ada@example.org")
    shop.bus.run_pending()
    return shop, uid


def _order_events(shop):
    return [m for m in shop.bus.published if m["topic"] == "order.created"]


def test_a_retry_returns_the_same_order():
    shop, uid = _shop_with_user()
    first = shop.orders.create_order(uid, 500, request_id="r-1")
    again = shop.orders.create_order(uid, 500, request_id="r-1")
    assert again == first
    assert len(shop.orders.orders_for(uid)) == 1


def test_a_retry_publishes_no_second_event():
    shop, uid = _shop_with_user()
    shop.orders.create_order(uid, 500, request_id="r-1")
    shop.orders.create_order(uid, 500, request_id="r-1")
    assert len(_order_events(shop)) == 1


def test_different_request_ids_make_different_orders():
    shop, uid = _shop_with_user()
    a = shop.orders.create_order(uid, 500, request_id="r-1")
    b = shop.orders.create_order(uid, 500, request_id="r-2")
    assert a != b
    assert len(shop.orders.orders_for(uid)) == 2


def test_without_a_request_id_every_call_is_a_new_order():
    shop, uid = _shop_with_user()
    shop.orders.create_order(uid, 500)
    shop.orders.create_order(uid, 500)
    assert len(shop.orders.orders_for(uid)) == 2


def test_a_retry_after_a_failed_first_attempt_creates_the_order():
    shop, uid = _shop_with_user()
    shop.orders.store.fail_next_write()
    with pytest.raises(StoreError):
        shop.orders.create_order(uid, 500, request_id="r-1")
    order_id = shop.orders.create_order(uid, 500, request_id="r-1")
    assert [o["order_id"] for o in shop.orders.orders_for(uid)] == [order_id]
    assert len(_order_events(shop)) == 1
