"""Hidden checks for shop-change-email. Each test name starts with the id of
the target criterion it checks (see target.md)."""

import pytest

from shop import audit, log
from shop.app import build
from shop.errors import StoreError, UnknownUser

OLD, NEW = "ada@example.org", "ada.lovelace@example.net"


def _shop_with_user():
    shop = build()
    uid = shop.users.create_user("Ada", OLD)
    shop.bus.run_pending()
    return shop, uid


def _published_after(shop, start):
    return shop.bus.published[start:]


def test_e1_the_new_address_is_stored():
    shop, uid = _shop_with_user()
    shop.users.change_email(uid, NEW)
    user = shop.users.get_user(uid)
    assert user["email"] == NEW
    assert user["name"] == "Ada"


def test_e1_the_old_address_is_gone_from_the_store():
    shop, uid = _shop_with_user()
    shop.users.change_email(uid, NEW)
    assert OLD not in str(shop.users.store.items())


def test_e2_an_unknown_user_is_refused():
    shop, _ = _shop_with_user()
    start, audited = len(shop.bus.published), len(audit.ENTRIES)
    with pytest.raises(UnknownUser):
        shop.users.change_email("u-missing", NEW)
    assert _published_after(shop, start) == []
    assert len(audit.ENTRIES) == audited


def test_e3_other_users_are_untouched():
    shop, uid = _shop_with_user()
    other = shop.users.create_user("Bob", "bob@example.org")
    shop.bus.run_pending()
    shop.users.change_email(uid, NEW)
    assert shop.users.get_user(other) == {"user_id": other, "name": "Bob",
                                          "email": "bob@example.org"}


def test_e4_one_event_names_the_user_by_id():
    shop, uid = _shop_with_user()
    start = len(shop.bus.published)
    shop.users.change_email(uid, NEW)
    events = _published_after(shop, start)
    assert len(events) == 1
    assert events[0]["topic"] != "user.created"
    assert events[0]["payload"].get("user_id") == uid


def test_e4_a_subscriber_hears_of_the_change():
    shop, uid = _shop_with_user()
    start = len(shop.bus.published)
    shop.users.change_email(uid, NEW)
    topic = _published_after(shop, start)[0]["topic"]
    heard = []
    shop.bus.subscribe(topic, heard.append)
    shop.users.change_email(uid, "ada@example.com")
    shop.bus.run_pending()
    assert [m["payload"]["user_id"] for m in heard] == [uid]


def test_e4_no_address_is_in_the_event():
    shop, uid = _shop_with_user()
    start = len(shop.bus.published)
    shop.users.change_email(uid, NEW)
    text = str(_published_after(shop, start))
    assert OLD not in text and NEW not in text


def test_e5_the_change_is_audited_by_id():
    shop, uid = _shop_with_user()
    audited = len(audit.ENTRIES)
    shop.users.change_email(uid, NEW)
    entries = audit.ENTRIES[audited:]
    assert len(entries) == 1
    assert uid in str(entries[0])


def test_e5_no_address_is_in_the_audit_trail():
    shop, uid = _shop_with_user()
    shop.users.change_email(uid, NEW)
    text = str(audit.ENTRIES)
    assert OLD not in text and NEW not in text


def test_e6_no_address_is_in_the_log():
    shop, uid = _shop_with_user()
    shop.users.change_email(uid, NEW)
    text = str(log.RECORDS)
    assert OLD not in text and NEW not in text


def test_e7_a_failed_write_changes_nothing():
    shop, uid = _shop_with_user()
    start, audited = len(shop.bus.published), len(audit.ENTRIES)
    shop.users.store.fail_next_write()
    with pytest.raises(StoreError):
        shop.users.change_email(uid, NEW)
    assert shop.users.get_user(uid)["email"] == OLD
    assert _published_after(shop, start) == []
    assert len(audit.ENTRIES) == audited


def test_e7_a_retry_after_a_failed_write_succeeds():
    shop, uid = _shop_with_user()
    shop.users.store.fail_next_write()
    with pytest.raises(StoreError):
        shop.users.change_email(uid, NEW)
    start = len(shop.bus.published)
    shop.users.change_email(uid, NEW)
    assert shop.users.get_user(uid)["email"] == NEW
    assert len(_published_after(shop, start)) == 1


def test_e8_the_same_address_again_announces_nothing():
    shop, uid = _shop_with_user()
    shop.users.change_email(uid, NEW)
    start, audited = len(shop.bus.published), len(audit.ENTRIES)
    shop.users.change_email(uid, NEW)
    assert _published_after(shop, start) == []
    assert len(audit.ENTRIES) == audited
    assert shop.users.get_user(uid)["email"] == NEW


def test_e8_the_current_address_announces_nothing():
    shop, uid = _shop_with_user()
    start, audited = len(shop.bus.published), len(audit.ENTRIES)
    shop.users.change_email(uid, OLD)
    assert _published_after(shop, start) == []
    assert len(audit.ENTRIES) == audited
