# Data assessment — 2026-10-23

## Sources inspected

- [TTC Bus Delay Data](https://open.toronto.ca/dataset/ttc-bus-delay-data/)
- [Delay catalogue metadata](https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/package_show?id=ttc-bus-delay-data)
- [TTC routes and schedules metadata](https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/package_show?id=ttc-routes-and-schedules)
- [Merged GTFS successor](https://open.toronto.ca/dataset/merged-gtfs-ttc-routes-and-schedules/)

The delay catalogue lists annual Excel workbooks for 2014–2024 and combined resources since 2025. This audit examines only the combined CSV. Its metadata describes a monthly refresh cadence; this is not proof of individual files' historical publication timestamps or daily completeness. The older GTFS catalogue points to a merged feed and describes updates approximately every six weeks. Historical schedule coverage has not been verified.

The portal links the [Open Government Licence – Toronto](https://open.toronto.ca/open-data-license/). The inspected older GTFS metadata reports `license_id=notspecified`; confirm the applicable resource terms before redistributing schedules. This repository distributes code and aggregate diagnostics, not raw data.

## Snapshot evidence

Resource: `b5725365-9252-4bfe-b6f4-cda7ddf74341`.

SHA-256: `1474f16414e63aaeab58714c236446ea370f5e00e072a3b97fdfeb1f079cd8fe`.

102,257 rows; 100,547 normalize successfully. Quarantine includes 1,708 invalid route strings and two ambiguous/nonexistent local times. There are 298 exact duplicate candidates excluding `_id`; these remain present because indistinguishable source rows may represent separate events. Blank counts: Line 1,241; Bound 21,327. Parse success is not semantic verification of bus routes.

## Field contract

| Source | Normalized meaning | Treatment |
| --- | --- | --- |
| Date + Time | Event start, Toronto local time | Convert to UTC; quarantine ambiguous/nonexistent times |
| Line | Leading numeric route identifier | Preserve source text in Bronze; require positive numeric prefix |
| Code | Reported incident code | Required; event inclusion taxonomy remains to be reviewed |
| Min Delay | Reported delay duration | Finite and nonnegative; never an arrival-time label |
| _id | Source-generated identifier | Not assumed stable across revisions |
| Day, Station, Min Gap, Bound, Vehicle | Source context | Retained in Bronze; not model features |

No historical availability timestamp is invented. Every normalized row has a null `available_at` until an evidence-backed policy exists.

## Feasibility decision

**Not ready for supervised risk training.** No positive-rate estimate is possible without a trustworthy denominator of service windows. The audit does not establish that every date is completely reported, that route IDs correspond to active buses, or that historical schedules and revisions can be reconstructed.

Required evidence: dated schedule snapshots with valid service calendars; explicit event inclusion criteria; a coverage ledger with reasons; and publication records or a justified conservative lag policy. A historical lag is an assumption to disclose and stress-test, not a replacement for evidence.

Do not construct negatives from the current route list or silently infer completeness from the presence of some events on a date. If the hourly task remains infeasible, assess a narrower route/date cohort before changing the target.
