"""Errors the services raise."""


class UnknownUser(LookupError):
    """No user with that id is known to this service."""


class StoreError(RuntimeError):
    """A store could not complete a read or write."""
