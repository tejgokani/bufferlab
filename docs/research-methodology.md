# Research methodology

## Research Mode matrix

`bufferlab research` / F10 builds a full-factorial design: **algorithm × offered load (% of link capacity) × queue capacity** with
`N` independent replications. Offered-load percentages are converted to packet rates from the link bandwidth and packet size;
delivered throughput is always measured. Default factors: Drop-Tail/RED/CoDel; 50, 75, 100, 125, 150 %; 10 / 50 / 250 packets (small / medium / large).

## Replications and seeds

Replication `k` uses seed `base_seed + k`. The same `k` yields the same arrival process for every algorithm (common random numbers),
so differences between algorithms within a replication are not caused by different traffic. Same config + same seed ⇒ identical results.

## Statistics

Per point: n, mean, sample SD and 95 % t-interval (see `metrics.md`). With n = 1 only the single value is shown. Overlapping intervals are reported
as "not distinguishable from run-to-run variation at this sample size"; non-overlapping intervals are reported as such and explicitly *not*
as a significance test.

## Report

Objective · Configuration · Algorithms (with resolved parameters) · Methodology · Metrics · Results table · Comparative observations ·
Limitations · Questions for further investigation. Observations are labelled *automated interpretation*, are generated only from measured
values, and never claim an algorithm is generally better. Reports are exported as Markdown / text / JSON / CSV and contain the spec needed to rerun them.

## Threats to validity

Open-loop traffic; single bottleneck; simplified RED/CoDel; finite run length and warm-up choice; results depend on chosen traffic model
and parameters. Do not cite BufferLab output as measurements of real networks or as reproductions of published results.
