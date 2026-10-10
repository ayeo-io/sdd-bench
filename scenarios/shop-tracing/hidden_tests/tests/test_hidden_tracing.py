from shop import log
from shop.app import build


def _records_for(user_id):
    return [r for r in log.RECORDS if r.get("user_id") == user_id]


def test_a_given_trace_id_reaches_every_service():
    shop = build()
    uid = shop.users.create_user("Ada", "ada@example.org", trace_id="t-1")
    shop.bus.run_pending()
    records = _records_for(uid)
    assert {r["service"] for r in records} == {"users", "orders", "subscriptions"}
    assert {r.get("trace_id") for r in records} == {"t-1"}


def test_every_event_caused_by_the_request_carries_the_trace_id():
    shop = build()
    shop.users.create_user("Ada", "ada@example.org", trace_id="t-1")
    shop.bus.run_pending()
    topics = {m["topic"] for m in shop.bus.published}
    assert {"user.created", "subscription.created"} <= topics
    assert {m["headers"].get("trace_id") for m in shop.bus.published} == {"t-1"}


def test_a_missing_trace_id_is_made_up_and_shared_by_the_whole_request():
    shop = build()
    a = shop.users.create_user("Ada", "ada@example.org")
    b = shop.users.create_user("Bob", "bob@example.org")
    shop.bus.run_pending()
    a_ids = {r.get("trace_id") for r in _records_for(a)}
    b_ids = {r.get("trace_id") for r in _records_for(b)}
    assert len(a_ids) == 1 and None not in a_ids and "" not in a_ids
    assert len(b_ids) == 1 and None not in b_ids and "" not in b_ids
    assert a_ids != b_ids


def test_requests_handled_together_keep_their_own_trace_ids():
    shop = build()
    a = shop.users.create_user("Ada", "ada@example.org", trace_id="t-a")
    b = shop.users.create_user("Bob", "bob@example.org", trace_id="t-b")
    shop.bus.run_pending()
    assert {r.get("trace_id") for r in _records_for(a)} == {"t-a"}
    assert {r.get("trace_id") for r in _records_for(b)} == {"t-b"}


def test_an_order_carries_its_trace_id():
    shop = build()
    uid = shop.users.create_user("Ada", "ada@example.org")
    shop.bus.run_pending()
    order_id = shop.orders.create_order(uid, 500, trace_id="t-o")
    records = [r for r in log.RECORDS if r.get("order_id") == order_id]
    assert records and {r.get("trace_id") for r in records} == {"t-o"}
    events = [m for m in shop.bus.published if m["topic"] == "order.created"]
    assert [m["headers"].get("trace_id") for m in events] == ["t-o"]


def test_a_retried_message_keeps_its_trace_id():
    shop = build()
    uid = shop.users.create_user("Ada", "ada@example.org", trace_id="t-r")
    shop.subscriptions.store.fail_next_write()
    shop.bus.run_pending()
    shop.bus.run_pending()
    subs = [r for r in _records_for(uid) if r["service"] == "subscriptions"]
    assert subs and {r.get("trace_id") for r in subs} == {"t-r"}
