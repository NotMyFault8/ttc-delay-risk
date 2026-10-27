# Data assessment — 2026-10-23

**Target revision, 2026-10-27:** the user authorized a model based on available incident records. The new primary research target is conditional recorded severity (`Min Delay >=15` given an incident), implemented and trained in `severity.py`. Its event-level labels do not require inferring unreported service hours. See [definition and real-data results](severity-model.md). The occurrence-risk blockers documented below still apply to the legacy target. The new evaluation is retrospective, with unknown historical publication times explicitly disclosed.

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

## Follow-up — 2026-10-27

The Airflow ingestion DAG fetched the live official bus-delay CSV successfully. Snapshot SHA-256: `2bc395f3c0db59010daf42bd97dcc6f2c3006c3646f58cf2d2cd42cba6e1b1f3`. It contains 107,349 rows for 2025-01-01 through 2026-09-30; 105,530 rows normalized and 1,819 were quarantined (1,817 invalid route values and two ambiguous/nonexistent Toronto local times). The snapshot is retained in the ignored Airflow data volume, not committed to this repository. The source remains a monthly refreshed incident feed; this snapshot does not establish complete service-hour reporting or publication times for individual records.

The TTC routes-and-schedules CKAN metadata was checked on 2026-10-27. It describes updates approximately every six weeks, reports a resource modification on 2026-10-26, and lists its license as unspecified. The official CKAN ZIP download returned HTTP 502 during this follow-up. The legacy TTC URL returned a 22-byte empty ZIP. The [Transitland TTC feed archive](https://www.transit.land/data/feeds/f-dpz8-ttc) lists more than 100 versions, including versions covering 2025–2026, but its [archive documentation](https://www.transit.land/data/feeds/archive) says downloading historical ZIPs requires Hobbyist/Academic or Enterprise access. The City’s [merged GTFS page](https://open.toronto.ca/dataset/merged-gtfs-ttc-routes-and-schedules/) identifies Open Government Licence - Toronto, while the older package metadata inspected above does not specify a license; confirm which feed and terms apply before redistributing any schedule snapshots.

Three historical GTFS ZIPs were recovered from Internet Archive captures of the City’s public feed and placed in the ignored Airflow data volume. Their files, SHA-256 hashes, archive capture timestamps, and effective date spans are recorded in `data/gtfs/schedule-manifest.json` and `data/gtfs/archive-audit.json` (inside that volume):

| Archived at (UTC) | GTFS service span | SHA-256 |
| --- | --- | --- |
| 2025-04-06 10:11:07 | 2025-03-30 to 2025-05-10 | `36a5e412eb52a1b4f92ca4f1444f3e15aae234245b38bd1dcd11cd4ce39073b3` |
| 2025-08-25 04:30:07 | 2025-08-31 to 2025-10-11 | `01feb720067c56fe63fc53bb5906577b59c37d6d275ae153f68eb5e068ddb922` |
| 2026-06-03 05:13:51 | 2026-06-07 to 2026-06-20 | `ba937f764d02e85a8137254b092e5ea771b2e91b840b4f1a908cf11e7c2f7bb8` |

All three archives passed ZIP CRC checks, identify `America/Toronto` as the agency timezone, and produce route-hour windows with the project's GTFS parser. Sample dates produced 3,546 windows across 195 routes (2025-04-07), 3,206 across 174 routes (2025-09-01), and 3,743 across 205 routes (2026-06-08). The valid spans are discontinuous and leave most of 2025-01-01 through 2026-09-30 without historical schedules. A current CKAN download attempt returned a 22-byte empty ZIP, so it could not extend schedule history. Transitland's archived versions provide additional date/hash metadata, but their ZIP contents remain unavailable without an eligible account plan.

The official bus-delay package metadata reports a monthly refresh rate but has blank notes and no collection-method or limitations statement. `data/ttc/coverage-audit.json` (inside the Airflow data volume) records daily incident counts and their overlap with these three GTFS spans. The latest ingested snapshot has at least one recorded incident on all 638 dates in its date range. This is an internal nonempty-date check only; it does not verify reporting completeness for every route-hour or justify labeling a missing row as no delay. The source page also currently warns of intermittent CKAN outages. No official incident publication timestamps were found. The archive capture dates support only when a specific schedule snapshot was observable, not when TTC first published that schedule.

**The legacy route-hour occurrence-risk target remains blocked.** Some historical service-window schedules were acquired, but most of the delay-data period has no usable schedule snapshot. No evidence establishes that route-hours without a row mean no reportable delay, and no availability policy for individual historical records is substantiated by the monthly cadence alone. Keep its evidence flags unverified. The user subsequently authorized the separately documented incident-conditional severity target; this does not resolve the blockers for occurrence risk.

## Follow-up — 2026-10-27: Kaggle 2023 workbook and realtime feed

Inspected `/Users/heartbreaker/Downloads/ttc-bus-delay-data-2023.xlsx.zip` in place; the downloaded archive SHA-256 is `df94ecfc4d0c7aff7f3824b3b5cd76e5cbbb41676f1a67c23b8ff65a8ddd6f4e`. It contains one worksheet (`2023`) with 50,913 data rows and columns `Date`, `Route`, `Time`, `Day`, `Location`, `Incident`, `Min Delay`, `Min Gap`, `Direction`, and `Vehicle`. The actual date span is 2023-01-01 through 2023-11-30, so December is absent. There are 261 distinct route values, 13 incident categories, 187 exact duplicate rows, no blanks in Date, Time, Incident, Min Delay, Min Gap, Location or Vehicle, and no negative or nonnumeric delay/gap values. Delay and gap contain zero values (4,120 and 4,321 rows respectively); direction includes 8,775 blanks and several unusual one-off values.

This workbook is a potentially useful *event-history extension*: its route, local date/time, incident type, and delay fields can be mapped into the event representation, after validating timezone/DST handling, route values, duplicate policy, and the mapping from `Incident` to the current feed's `Code` taxonomy. Do not concatenate it blindly with the 2025+ feed: schemas and incident taxonomies differ, the intervening 2024 period remains absent, and there is no record-level publication/availability timestamp. Most importantly, event rows alone do not establish negative labels or complete route-hour reporting. Training the existing route-hour risk target still requires 2023 as-of GTFS service schedules, reviewed route-hour coverage, a reviewed incident allowlist, and a defensible historical availability policy. Thus this file improves event history but does not unblock supervised training of the current target.

The official TTC BusTime GTFS-Realtime service exposes surface vehicle-position, trip-update, and alert feeds. Transitland's feed record reported a successful recent fetch (about one minute before it was checked); the City catalogue identifies Toronto's Open Government Licence, while its page was showing CKAN outage warnings during this audit. A realtime feed is a changing current-state snapshot, not a historical release for the 2023 period. It can support operational nowcasting or serve as as-of features if captured with retrieval timestamps and joined to contemporaneous schedules. Repeated immutable snapshots plus subsequent observed outcomes could form future training data for a separately defined short-horizon model. For the current 03:30 next-day route-hour target, same-day realtime values would be post-cutoff and must not enter features. No realtime payload was archived in this audit.
