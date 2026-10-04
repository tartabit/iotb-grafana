# 2026-08-30
Added the IoT Bridge NATS dashboard for JetStream throughput, consumer backlog, ACK progress, drain time, trigger worker capacity, queue and handler latency, failures, redeliveries, and reply outcomes. Added alerts for disconnected NATS clients, sustained consumer backlog growth, warning and critical trigger queue delay, ACK and fetch failures, and sustained redeliveries. Corrected counter queries to use the metric names exported by IoT Bridge.

# 2026-08-24
Added the IoT Bridge retention dashboard and alerts for stale sweepers, repeated errors, stale progress, falling-behind or stalled rules, and MongoDB operations approaching their configured timeout. Empty condition results are healthy for the five condition-based alerts; only the sweeper-stale alert treats missing data as a failure.

# 2026-01-05
Initial release
