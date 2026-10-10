# Target: shop-forget-user

A user can be forgotten across three stores with no shared transaction.
Production-grade means the deletion always finishes, never half-happens at
the source, cannot be undone by late or repeated messages, leaves an audit
trail with no personal data, and needs no change to the user service when a
fourth service starts holding user data.

## Behaviours

| Id | Given | When | Then |
|---|---|---|---|
| F1 | a user with orders and subscriptions | `delete_user` runs and events are delivered | the user, their orders and their subscriptions are gone |
| F2 | other users exist | one user is deleted | nothing about the others changes |
| F3 | no such user | `delete_user` is called | `UnknownUser` is raised |
| F4 | a downstream store fails during the deletion | events are delivered again | the deletion finishes and nothing is left pending |
| F5 | the deletion message is delivered twice | both are handled | no error, nothing left pending, nothing comes back |
| F6 | a new service subscribes to what `delete_user` publishes | a user is deleted | the new service hears of it, and the user service imports and holds no other service |
| F7 | a user has been deleted | an order or a subscription is attempted for them | `UnknownUser` is raised |
| F8 | a user is deleted | the deletion completes | each service that held data records its deletion in the audit trail, by id, with no name or email anywhere in the audit trail, the log or the events |
| F9 | a `user.created` for the user is still waiting to be retried when they are deleted | everything is delivered | the late `user.created` does not bring them back anywhere |
| F10 | the user service's store fails during `delete_user` | the call fails | the user still exists, nothing is announced, and downstream data is untouched |
| F11 | a user has been deleted | `delete_user` is called again | `UnknownUser` is raised |

Plus the quality part: `docs/target-quality.md`.
