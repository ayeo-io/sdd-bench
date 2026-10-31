# Target: shop-change-email

A customer can change the email address on their account. The change is
small and stays in one service, but it touches personal data. Production-grade
means the new address is stored, the old one is gone, other services hear of
the change without seeing either address, the removal of the old address is
on the audit trail, a failed write changes nothing, and a repeated request
announces nothing new.

## Behaviours

| Id | Given | When | Then |
|---|---|---|---|
| E1 | a user | `change_email` is called with a new address | `get_user` returns the new address and the same name |
| E2 | no such user | `change_email` is called | `UnknownUser` is raised, and nothing is published or audited |
| E3 | other users exist | one user's email is changed | nothing about the others changes |
| E4 | a user | their email is changed | one event about that user is published on the bus, naming the user by id, with neither address in it |
| E5 | a user | their email is changed | the audit trail records the change by user id, with neither address in it |
| E6 | a user | their email is changed | no log record holds either address |
| E7 | the user service's store fails during `change_email` | the call fails | the error is raised, the user keeps the old address, and nothing is published or audited |
| E8 | a user's email is already the address given | `change_email` is called with it again | the call succeeds, and nothing is published or audited a second time |

Plus the quality part: `docs/target-quality.md`.
