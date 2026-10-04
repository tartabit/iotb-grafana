# Retention dashboard

`library/dashboards/iotbridge-system-retention.json` retains dashboard UID
`iotb-system-retention`, its folder, target filter, existing retention panels,
30-second refresh, and six-hour default range. The rollover section sits between
retention health and rule progress. Its adaptive batch size and duration panels
require the adaptive-transfer version of `core-events`; the other rollover panels
continue to use the existing metrics.

## Reading the rollover section

- **Rollover phase / history:** idle, preparing, switching, draining, or dropping.
- **Draining records remaining / over time:** approximate old-generation count.
- **Rollover elapsed:** time since rollover was requested, not acceleration time.
- **Net drain rate:** negative five-minute derivative of the remaining-count
  gauge. Positive means shrinking; negative means growing. Both transfers and
  retention deletions contribute. Hourly samples during normal draining produce
  steps; acceleration samples every controller pass. Transitions can distort the
  estimate. It is not exact transfer throughput or an ETA.
- **Rollover errors:** counter increase over ten minutes. Zero is supplied for a
  missing error counter only when that reporter has phase telemetry. No phase
  telemetry stays missing, rather than falsely reporting healthy operation.
- **Adaptive transfer batch size:** next learned limit and the last batch's
  committed count. Starts at 500, adds 20 for a full batch under one second, and
  reduces by 20% for a batch over one second. Limits remain between 100 and 5,000;
  the byte cap and account size can keep the actual count below that limit.
- **Transfer batch duration:** last attempt's elapsed time, including index
  lookup, retries, and commit, excluding allocation sampling. The line at one
  second is a feedback target. The 20-second timeout still applies. These gauges
  retain the last attempt; they are not a live enabled indicator or counter.
- **Allocation:** active/draining total allocation, reusable bytes, and data/index
  bytes. Reusable space is still owned by its collection; these metrics are not
  PVC usage or filesystem free space. Dropping the old collection reclaims its
  allocation.

The **Rollover pod** filter applies only to the rollover section. Gauges are
grouped by target and pod name, so a pod restarting with a different IP continues
the same chart series. If old and new IP series briefly overlap, the most recently
scraped duration series selects one reporter within that pod before its gauges
are grouped. Phase values are not added across IPs. The drain-rate query merges
the gauge first, then estimates its derivative using one-minute samples over five
minutes. Error increases are calculated per original counter before summing by
pod, so restarts and IP changes do not create counter spikes.

Different controller pods remain separate. A former controller can continue
exposing its last state after ownership changes; scrape timestamps do not prove
fresh controller state. During an active rollover, select the pod whose elapsed
time continues advancing. There is no exported controller observation timestamp
to select the active pod automatically. The existing retention progress charts
also discard IP labels after their latest-run selection, retaining pod name and
the applicable rule, phase, or work kind.

The application **Retention → Rollover** page remains the source for acceleration
enabled/paused, newest draining timestamp, drop eligibility, and last-error text.
Those fields and cumulative transferred totals are not exported by the current
metrics. The dashboard deliberately does not infer enabled state, a
completion percentage, or a finish time.

## Validation and import

```powershell
python validate-dashboards.py
$env:PROMTOOL = 'C:\path\to\promtool.exe'
python -m unittest discover -s tests -p test_retention_dashboard.py -v
```

The focused tests check layout and dashboard identity, parse all panel queries,
and evaluate synthetic data for draining/growing/idle counts, multiple
controllers, all phases, error counter resets, and absent telemetry. This does
not establish live metric availability or Grafana rendering. Import the updated
dashboard through the normal project workflow to update Grafana; the source
change does not publish it or alter existing alert rules.
