# My Network: measure, then predict

`bufferlab network probe` (TUI: F8, key `p`) measures the network this computer is on; `bufferlab network predict`
(TUI: `r`) simulates that network at other loads. **Measured values and simulated values are always labelled separately.**

## What the probe does (real traffic — you are asked first)

1. **Idle:** 10 ICMP pings (system `ping`, no admin rights) to `1.1.1.1` → median RTT and packet loss.
2. **Loaded:** ~8 s of 4 parallel HTTPS downloads from `speed.cloudflare.com`, capped at 300 MB, with ~30 pings running at the same time
   → download throughput (mean over the steady part, first 1.5 s ignored), RTT and loss *under load*.

## How measurements become simulator parameters

| simulator input | derived from |
|---|---|
| link capacity | measured download throughput |
| propagation delay | idle RTT / 2 |
| buffer size (packets) | `(loaded RTT − idle RTT) × capacity / (1500 B × 8)`, clamped to 8…5000 — the latency growth under saturation is the standing queue |
| packet size | 1500 B |
| traffic | 4 open-loop sources, Poisson by default (bursty / constant selectable) |

Everything is recorded in the saved profile (and shown on screen), including a note when the buffer had to be assumed.

## Predictions

Default loads are 25 % … 200 % of the measured capacity (or give `--loads` in Mbps). For each load the simulator reports throughput,
packet-loss rate and queueing delay for Drop-Tail (what most routers do) or all three algorithms. Every simulation is stored as an ordinary run
(History, Compare, Export). The "knee" line states the lowest tested load at which loss exceeds 1 %.

## Limitations — read before trusting a number

* **Open-loop traffic.** Simulated sources keep sending when packets are lost (like UDP, video calls, many independent users). Real TCP backs off,
  so its loss would be lower and its throughput closer to capacity. Predictions are for *demand that does not adapt*.
* **Capacity is to one server.** The download rate is what you got to Cloudflare at that moment; Wi‑Fi, other devices, the server or the
  time of day can change it. Re-measure; one measurement is one sample.
* **Download direction only.** Upload capacity and upstream buffering are not measured.
* **Buffer size is inferred** from latency growth (assumes the queue that grew is the bottleneck's).
* **ICMP loss** is not what applications see; on a healthy link it is usually 0 % even under load, because TCP avoids loss.
* Single bottleneck, no cross-traffic model beyond the chosen arrival process.
