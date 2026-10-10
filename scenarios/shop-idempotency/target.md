# Target: shop-idempotency

A client can retry `create_order` safely. Production-grade means a retry is
safe after any failure, cannot be abused, and stays cheap as orders grow.

## Behaviours

| Id | Given | When | Then |
|---|---|---|---|
| I1 | an order was created with request id R | the same call is made again with R | the same order id comes back, there is still one order, and one `order.created` event |
| I2 | an order was created with R | a call is made with a different request id | a new order is created |
| I3 | no request id is given | the call is made twice | two orders are created, as before |
| I4 | the store fails on the first write | the client retries with R | exactly one order exists, with one event |
| I5 | the store fails part-way through the first attempt, after 1, 2 or 3 writes | the client retries with R | exactly one order exists, with one event, and the retry returns its id |
| I6 | R was used for one order | R is reused with a different amount or a different user | the call is refused with `ValueError` and nothing is created |
| I7 | a call with R is rejected because its amount is invalid | a valid call is made with R | the order is created: a rejected call does not use up its request id |
| I8 | orders exist with and without request ids | `orders_for` is called | it lists only orders, oldest first, each with its id, user and amount |
| I9 | the store holds hundreds of orders | a call with a request id is made | finding the request reads a handful of rows, not every order (`store.rows_read`) |

Plus the quality part: `docs/target-quality.md`.
