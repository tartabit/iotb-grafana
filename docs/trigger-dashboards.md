# Trigger performance dashboards

Overview, List, and Single use existing metrics; no exporter changes are needed.
Existing dashboard UIDs and the `accountId` / `triggerId` variable keys remain stable.
Panel titles and table headings are lowercase. Existing noise thresholds remain on
the throughput and complexity charts; List includes every trigger with recorded
executions during the selected time range.

## Operations share

Overview's two share charts show operations by account and by account/trigger.
They select the top 50 identities using total operations over the displayed range
at `end()`, keeping membership fixed across that range. Every remaining contributor
is included in `other`. The denominator includes all selected accounts' operations,
including work suppressed by the older charts' noise thresholds. Explicit percent
queries keep tooltip values meaningful; zero or unavailable totals produce gaps.

Operations are interpreter work, not CPU consumption. CPU, worker utilization, and
queue-delay panels are system-wide and do not follow the account filter. An absent
metric remains no data rather than being treated as zero.

## List and Single statistics

The List table and Single's comparison table use identical instant queries at the
selected range's end. Rows join on a composite account/trigger identity. Name maps
are deduplicated, with raw IDs used when mappings are missing. IDs remain in the
table data but are hidden from display so drilldown links stay unambiguous even
when names repeat. Clicking the trigger passes both IDs and absolute range bounds
to Single. Columns support numeric sorting, filtering, and pagination; the initial
sort is total operations descending.

Average complexity is total operations divided by recorded executions; average
duration is accumulated elapsed execution time divided by recorded executions.
Single pools sums, counts, and histogram buckets before calculating statistics
for multiple selected triggers. It does not average per-trigger means or p95s.

Both p95 and maximum are histogram estimates. Maximum uses quantile 1, which is
the upper edge of the highest occupied finite bucket, rather than the exact
maximum observed execution. Complexity buckets stop at 500,000 operations and
duration buckets stop at 20,000 milliseconds. Queries detect when the requested
quantile lies beyond that bound and return a numeric sentinel (500001 or 20001),
mapped to `>500,000 ops` or `>20 s`. These sentinel values are used only for
quantiles, sort above finite estimates, and tie with other overflow entries.
Average values are not capped. Missing statistics remain blank.

Finite-bucket selectors accept both integer labels (`500000`) and Prometheus 3's
normalized decimal labels (`500000.0`). This also applies to the executions
exceeding 20,000 / 500,000 operations panels. Those panels subtract the finite
cumulative bucket from `+Inf`, counting executions strictly above the threshold,
and retain ID fallbacks when name mappings are absent. They do not count
operation-limit aborts, which bypass histogram observation and are recorded as
`exec-limit` errors instead. The runtime limit is configurable and must not be
treated as equivalent to either fixed chart threshold.

Execution histograms can omit panic-aborted runs. Single's recorded failure
percentage instead uses all outcomes from `iotbridge_trigger_engine_errors`,
with `error="none"` treated as success. The category panel excludes successes.
The `(x)` markers remain on Single's process metrics and account-only action rate
because those panels cannot fully follow trigger selection.

Throughput queries use `rate(...[$__rate_interval]) * 60`; thresholds therefore
remain in per-minute units. Configure Grafana's Prometheus scrape interval to
match the actual scrape configuration. Donuts and complexity bars use selected-
range instant increases; retained top-10 donuts describe only their displayed
contributors, while the share charts include the full selected total.

## Verification

```powershell
python validate-dashboards.py
python -m unittest discover -s tests -v
# Also execute expressions against Prometheus's query engine:
$env:PROMTOOL = 'C:\path\to\promtool.exe'
python -m unittest discover -s tests -v
```

The optional Prometheus tests parse panel/variable expressions and evaluate
synthetic metrics for weighted statistics, histogram overflow with integer and
decimal bucket labels, exceeding-threshold counts, missing mappings,
duplicate names and replicated mappings, idle periods, counter resets, and
top-50-plus-other totals. Browser validation should additionally check column
sorting, hidden IDs, drilldown, range preservation, and selected-trigger parity.
Local fixture validation does not establish production metric availability.

Importing into the operational Grafana instance remains a separate step.
