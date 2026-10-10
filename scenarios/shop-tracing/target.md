# Target: shop-tracing

One request can be followed through every service. Production-grade means
the trace is correct when requests interleave, when messages are retried,
and when a message arrives from outside without one.

## Behaviours

| Id | Given | When | Then |
|---|---|---|---|
| T1 | `create_user` is called with trace id T | events are delivered | every log record about the user, in all three services, and every event the request caused (including `subscription.created`) carries T |
| T2 | no trace id, or an empty one, is given | the request is handled | a trace id is made up, shared by the whole request, and different for each request |
| T3 | two requests with different trace ids are made before events are delivered | events are delivered | each request's records carry its own trace id: no shared or global current trace |
| T4 | `create_order` is called, with or without a trace id | it completes | the log record and the `order.created` event carry the same trace id |
| T5 | a handler fails and its message is retried | the retry succeeds | the records it writes carry the original trace id |
| T6 | a message arrives with no trace id in its headers (from code that predates tracing) | it is handled | the handler's records and events get a fresh trace id, never none |
| T7 | existing callers pass no trace id | they run | behaviour is unchanged |

Plus the quality part: `docs/target-quality.md`.
