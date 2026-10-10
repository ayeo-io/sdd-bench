"""Hidden checks for shop-idempotency. Each test name starts with the id of
the target criterion it checks (see target.md)."""

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


def test_i1_a_retry_returns_the_same_order():
    shop, uid = _shop_with_user()
    first = shop.orders.create_order(uid, 500, request_id="r-1")
    again = shop.orders.create_order(uid, 500, request_id="r-1")
    assert again == first
    assert len(shop.orders.orders_for(uid)) == 1


def test_i1_a_retry_publishes_no_second_event():
    shop, uid = _shop_with_user()
    shop.orders.create_order(uid, 500, request_id="r-1")
    shop.orders.create_order(uid, 500, request_id="r-1")
    assert len(_order_events(shop)) == 1


def test_i2_different_request_ids_make_different_orders():
    shop, uid = _shop_with_user()
    a = shop.orders.create_order(uid, 500, request_id="r-1")
    b = shop.orders.create_order(uid, 500, request_id="r-2")
    assert a != b
    assert len(shop.orders.orders_for(uid)) == 2


def test_i3_without_a_request_id_every_call_is_a_new_order():
    shop, uid = _shop_with_user()
    shop.orders.create_order(uid, 500)
    shop.orders.create_order(uid, 500)
    assert len(shop.orders.orders_for(uid)) == 2


def test_i4_a_retry_after_a_failed_first_attempt_creates_the_order():
    shop, uid = _shop_with_user()
    shop.orders.store.fail_next_write()
    with pytest.raises(StoreError):
        shop.orders.create_order(uid, 500, request_id="r-1")
    order_id = shop.orders.create_order(uid, 500, request_id="r-1")
    assert [o["order_id"] for o in shop.orders.orders_for(uid)] == [order_id]
    assert len(_order_events(shop)) == 1


@pytest.mark.parametrize("ok_writes", [1, 2, 3])
def test_i5_a_failure_part_way_through_never_leaves_a_duplicate(ok_writes):
    shop, uid = _shop_with_user()
    shop.orders.store.fail_write_after(ok_writes)
    try:
        first = shop.orders.create_order(uid, 500, request_id="r-1")
    except StoreError:
        first = None
    order_id = shop.orders.create_order(uid, 500, request_id="r-1")
    if first is not None:
        assert order_id == first
    assert [o["order_id"] for o in shop.orders.orders_for(uid)] == [order_id]
    assert len(_order_events(shop)) == 1


def test_i6_reusing_a_request_id_for_a_different_order_is_refused():
    shop, uid = _shop_with_user()
    shop.orders.create_order(uid, 500, request_id="r-1")
    with pytest.raises(ValueError):
        shop.orders.create_order(uid, 999, request_id="r-1")
    assert len(shop.orders.orders_for(uid)) == 1


def test_i6_another_user_never_gets_the_first_users_order():
    # Refusing, or treating request ids as each user's own, are both fine.
    # Handing one user's order to another is not.
    shop, uid = _shop_with_user()
    other = shop.users.create_user("Bob", "bob@example.org")
    shop.bus.run_pending()
    first = shop.orders.create_order(uid, 500, request_id="r-1")
    try:
        theirs = shop.orders.create_order(other, 500, request_id="r-1")
    except ValueError:
        assert shop.orders.orders_for(other) == []
    else:
        assert theirs != first
        assert [o["order_id"] for o in shop.orders.orders_for(other)] == [theirs]
    assert [o["order_id"] for o in shop.orders.orders_for(uid)] == [first]


def test_i7_a_rejected_order_does_not_use_up_its_request_id():
    shop, uid = _shop_with_user()
    with pytest.raises(ValueError):
        shop.orders.create_order(uid, -5, request_id="r-1")
    order_id = shop.orders.create_order(uid, 500, request_id="r-1")
    assert [o["order_id"] for o in shop.orders.orders_for(uid)] == [order_id]


def test_i8_orders_for_lists_only_orders():
    shop, uid = _shop_with_user()
    shop.orders.create_order(uid, 500, request_id="r-1")
    shop.orders.create_order(uid, 700)
    orders = shop.orders.orders_for(uid)
    assert [o["amount_pence"] for o in orders] == [500, 700]
    assert all(set(o) >= {"order_id", "user_id", "amount_pence"} for o in orders)


def test_i9_a_retry_does_not_read_every_order():
    shop, uid = _shop_with_user()
    for _ in range(300):
        shop.orders.create_order(uid, 100)
    shop.orders.create_order(uid, 500, request_id="r-1")
    before = shop.orders.store.rows_read
    shop.orders.create_order(uid, 500, request_id="r-1")
    shop.orders.create_order(uid, 600, request_id="r-2")
    assert shop.orders.store.rows_read - before < 20
