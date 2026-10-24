# Metric definitions (schema version 1)

Let `w0` be the warm-up length and `end` the end of the run (`duration`, or the last processed event time if
the run stopped early). The *window* is `[w0, end]`; its length is `W`.

## Packet cohort

A packet is in the **cohort** iff its arrival time ≥ `w0`. Every cohort packet ends in exactly one state:

* **delivered** – finished transmission by `end`;
* **dropped** – discarded (overflow, early/RED, or AQM/CoDel head drop) by `end`;
* **unresolved** – still queued or in service at `end`.

`generated = delivered + dropped + unresolved` (verified by tests). Unresolved packets are never counted as dropped.

| metric | definition |
|---|---|
| Generated / admitted / delivered / dropped | counts over the cohort (*admitted* = accepted into the buffer) |
| Packet delivery ratio | `delivered / generated` |
| Packet-loss rate | `dropped / generated` (denominator: all cohort packets, including unresolved) |
| Offered load | nominal: `rate × size × 8` (Mbps) and % of capacity; *measured offered* = generated bits / W |
| Delivered throughput | bits whose **transmission completed** in the window / W (a time-window rate: includes packets that arrived during warm-up) |
| Link utilisation | busy time inside the window / W |
| Queueing delay | `service_start − enqueue_time` of delivered cohort packets; reported as mean, median, p95 (linear interpolation) and max |
| Total delay (one-way) | mean queueing delay + service time + propagation delay |
| Queue occupancy | packets waiting (excluding the one in service); time-weighted average and maximum over the window |
| Queue utilisation | average occupancy / capacity |
| Overflow events | number of arrivals dropped because the buffer was full (cohort) |

Ratios are `null` when the denominator is zero (e.g. no traffic); delay statistics are `null` when no packet
was delivered. They are never reported as 0.

## Not the same thing

* **Queueing delay** – time waiting in the buffer. **Propagation delay** – constant link latency. **Total packet
  delay** – both plus transmission. **RTT** – round trip; BufferLab does not model one and never labels
  queueing delay as RTT.

## Time series

200 bins over the whole run (including warm-up, drawn dim in the TUI): mean throughput, time-averaged queue
length, mean queueing delay of departures, link utilisation, drop counts and arrival counts per bin. Live
(in-progress) summary values are marked `approximate`; percentiles then use the most recent 20,000 delivered packets.

