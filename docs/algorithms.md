# Algorithms

All implement `algorithms.base.QueueManager`: `enqueue(pkt, now) -> DropReason | None`, `dequeue(now) -> DequeueResult`.
They take time and an injected seeded RNG as inputs and have no other state, so they are unit-tested in isolation.
`algorithms/registry.py` declares each algorithm's parameters (used for validation, defaults, and the TUI forms).
New algorithms (PIE, FQ-CoDel…) need: a `QueueManager` subclass, a builder, and an entry in `ALGORITHMS`.

## Drop-Tail

Finite FIFO of `capacity` packets; an arrival to a full buffer is dropped (`overflow`).

## RED (Floyd & Jacobson, 1993) — packet mode, drop only

With `q` = packets waiting:

* average: `avg ← (1−w)·avg + w·q` on each arrival to a non-empty queue
* after an idle period: `avg ← (1−w)^m · avg`, `m = (now − t_idle)/s`, `s` = one packet transmission time
* `avg < min_th`: admit, `count = −1`
* `min_th ≤ avg < max_th`: `count += 1`, `pb = max_p·(avg−min_th)/(max_th−min_th)`, `pa = pb/(1 − count·pb)`
  (`pa = 1` if `count·pb ≥ 1`); drop with probability `pa`, then `count = 0`
* `avg ≥ max_th`: drop, `count = 0` (with `gentle`, probability rises from `max_p` to 1 over `[max_th, 2·max_th)`)
* a full buffer forces an `overflow` drop regardless of `avg`.

Defaults: `min_th = 25%` and `max_th = 75%` of capacity (resolved values are stored with each run), `max_p = 0.1`,
`w = 0.01` (the paper suggests 0.002 for long-running links; 0.01 adapts within the short default runs).

**Deviations:** idle = "waiting queue empty" instead of "link idle"; no ECN, no adaptive/“Adaptive RED” max_p; thresholds fixed in packets.
Not validated against any operating-system implementation.

## CoDel (RFC 8289 §5 pseudo-code)

State `first_above_time, drop_next, count, lastcount, dropping`. At dequeue, sojourn = `now − enqueue_time`.

1. If sojourn < `target` or backlog ≤ one MTU, `first_above_time` is cleared.
2. Otherwise, the first time this happens `first_above_time = now + interval`; the packet is *droppable* once `now ≥ first_above_time`
   (delay above target for a whole interval).
3. Not dropping and droppable ⇒ drop the head, enter dropping, `count` resumes from `count − lastcount` if re-entering within
   16 intervals (else 1), `drop_next = now + interval/√count`.
4. While dropping: while `now ≥ drop_next`, drop head, `count += 1`, `drop_next += interval/√count`; leave dropping when sojourn falls below target or the queue empties.

Defaults `target = 5 ms`, `interval = 100 ms`. Buffer overflow tail-drops arrivals and is counted as `overflow`, not as a CoDel decision.

**Deviations:** drop only (no ECN); MTU = configured packet size; `math.sqrt` rather than the integer reciprocal-sqrt tables of the Linux kernel.
Not validated against `sch_codel` or the ns-3 model.

## Validation performed

Unit tests drive each algorithm through hand-computed sequences (RED's EWMA, idle decay, probability regimes, count-based
uniformisation; CoDel's arm → wait interval → first drop → `interval/√count` spacing → exit → hysteresis). The simulator is checked
against closed-form M/D/1 queueing delay (`ρ·S/(2(1−ρ))`). No comparison against published results or external simulators has been performed.
