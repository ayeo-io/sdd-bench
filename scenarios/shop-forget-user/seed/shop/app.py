"""Wires the three services to one bus."""

from __future__ import annotations

from dataclasses import dataclass

from shop.bus import Bus
from shop.orders import OrderService
from shop.subscriptions import SubscriptionService
from shop.users import UserService


@dataclass
class Shop:
    """The three services and the bus they share."""

    bus: Bus
    users: UserService
    orders: OrderService
    subscriptions: SubscriptionService


def build() -> Shop:
    """A fresh shop with empty stores."""
    bus = Bus()
    return Shop(bus=bus, users=UserService(bus), orders=OrderService(bus),
                subscriptions=SubscriptionService(bus))
