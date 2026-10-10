# Conventions

- Each service owns its own store. No service reads or writes another
  service's store, and no service calls another service directly: they
  talk only through the bus.
- Events are named `<thing>.<what happened>`, in the past tense, such as
  `user.created`.
- The bus delivers at least once. A handler can see the same message
  twice and must give the same result.
- A handler that cannot finish should raise, so the bus delivers the
  message again. It must not swallow the error.
- Amounts are whole pence (`int`). Never floats.
- Personal data is a user's name and email. It lives only in the user
  service's store. It never goes into the log, the audit trail or an
  event.
- Every deletion of personal data, and every deletion of records about a
  person, is recorded with `shop.audit.record(...)`. The audit trail is
  kept for good, so an audit entry holds ids, never personal data.
- Tests use `shop.app.build()` for a fresh shop, and call
  `bus.run_pending()` to deliver events.
