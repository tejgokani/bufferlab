# Simulation model

BufferLab simulates one bottleneck: **sources → queue manager → link → destination**.

## Time and events

* Simulated time is a float number of seconds. The simulator never sleeps; it pops the next event
  from a binary heap (`core/scheduler.py`) and jumps the clock to it, so runs are much faster than real time.
* Two event kinds exist: `ARRIVAL` (a source emits a packet) and `DEPARTURE` (the packet in service
  finishes transmission).
* **Ties.** Events at exactly the same timestamp are ordered by kind (departure first, so a slot freed at *t*
  is available to a packet arriving at *t*), then by insertion order. Runs are therefore deterministic.
* **Termination.** Events with time > `duration` are never processed. A departure scheduled after the
  end leaves its packet *unresolved* (see below).

## Link

`service_time = packet_size_bytes × 8 / capacity_bps`. One packet is transmitted at a time.
`offered_load_bps = arrival_rate_pps × packet_size_bytes × 8`. In the UI/CLI the load is entered as a
percentage of capacity and converted: `pps = load% / 100 × capacity_bps / (packet_size_bytes × 8)`.
Offered load is a nominal input; delivered throughput is measured and may be lower.

## Buffer

The buffer holds packets *waiting*; the packet in service is not counted. Capacity is in packets.
An arriving packet is offered to the queue manager; if admitted and the link is idle it is dequeued
immediately (queueing delay 0). When the link becomes free the queue manager's `dequeue` picks the
next packet (CoDel may drop head packets there).

## Traffic (`core/traffic.py`)

The total rate is split equally across `n_sources`. Each source has its own RNG stream derived from the seed
(`sha256(seed:stream)`), so adding a consumer never perturbs another stream.

| model | behaviour |
|---|---|
| `constant` | period 1/rate, random initial phase per source |
| `poisson` | exponential inter-arrivals, mean 1/rate |
| `bursty` | on/off Markov-modulated Poisson: ON/OFF durations exponential (defaults 200 ms / 800 ms means); Poisson at peak rate `rate·(on+off)/on` during ON, so the long-run average equals `rate` |

## Propagation delay

Optional constant one-way delay added to *total* packet delay reporting. It does not change queueing
(open-loop sources have no feedback), and no packet ever waits for it to end the simulation.

## What is not modelled

* TCP or any closed-loop congestion control, retransmissions, ACK clocking, RTT. Sources are open-loop.
* Multiple hops, reverse paths, link errors, packet-size distributions (all packets are the same size).
* ECN marking (RED and CoDel only drop).

Therefore results say nothing about realistic TCP throughput, only about how a single queue behaves under the
configured open-loop arrivals.

## Safety limits

`max_events` (default 5,000,000) stops a run early (`terminated = event_limit`); metrics then cover only the
simulated portion. Cancellation is checked every 1024 events.
