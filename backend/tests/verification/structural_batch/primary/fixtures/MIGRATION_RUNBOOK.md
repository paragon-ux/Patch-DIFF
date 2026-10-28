# Settlement Protocol v3 Nanosecond & Quorum Migration Runbook

## 1. Executive Summary

- **Active Wire Default**: `v2` (`epoch_unit = sec`)
- **Allowed Idempotency Scopes**: `GLOBAL, PARTITION`
- **Critical Rule Cohort**: `rule_04, rule_11, rule_19, rule_27`
- **Canary Tenant Cohort**: `ten_006, ten_013, ten_018`

## 2.1 Pre-Flight Verification Gate #01

Verify partition telemetry and replication watermark for gate `01` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-01-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-01-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-01-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.2 Pre-Flight Verification Gate #02

Verify partition telemetry and replication watermark for gate `02` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-02-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-02-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-02-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.3 Pre-Flight Verification Gate #03

Verify partition telemetry and replication watermark for gate `03` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-03-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-03-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-03-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.4 Pre-Flight Verification Gate #04

Verify partition telemetry and replication watermark for gate `04` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-04-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-04-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-04-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.5 Pre-Flight Verification Gate #05

Verify partition telemetry and replication watermark for gate `05` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-05-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-05-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-05-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.6 Pre-Flight Verification Gate #06

Verify partition telemetry and replication watermark for gate `06` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-06-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-06-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-06-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.7 Pre-Flight Verification Gate #07

Verify partition telemetry and replication watermark for gate `07` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-07-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-07-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-07-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.8 Pre-Flight Verification Gate #08

Verify partition telemetry and replication watermark for gate `08` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-08-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-08-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-08-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.9 Pre-Flight Verification Gate #09

Verify partition telemetry and replication watermark for gate `09` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-09-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-09-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-09-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.10 Pre-Flight Verification Gate #10

Verify partition telemetry and replication watermark for gate `10` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-10-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-10-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-10-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.11 Pre-Flight Verification Gate #11

Verify partition telemetry and replication watermark for gate `11` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-11-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-11-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-11-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.12 Pre-Flight Verification Gate #12

Verify partition telemetry and replication watermark for gate `12` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-12-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-12-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-12-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.13 Pre-Flight Verification Gate #13

Verify partition telemetry and replication watermark for gate `13` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-13-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-13-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-13-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.14 Pre-Flight Verification Gate #14

Verify partition telemetry and replication watermark for gate `14` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-14-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-14-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-14-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.15 Pre-Flight Verification Gate #15

Verify partition telemetry and replication watermark for gate `15` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-15-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-15-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-15-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.16 Pre-Flight Verification Gate #16

Verify partition telemetry and replication watermark for gate `16` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-16-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-16-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-16-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.17 Pre-Flight Verification Gate #17

Verify partition telemetry and replication watermark for gate `17` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-17-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-17-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-17-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.18 Pre-Flight Verification Gate #18

Verify partition telemetry and replication watermark for gate `18` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-18-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-18-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-18-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.19 Pre-Flight Verification Gate #19

Verify partition telemetry and replication watermark for gate `19` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-19-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-19-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-19-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 2.20 Pre-Flight Verification Gate #20

Verify partition telemetry and replication watermark for gate `20` before
promoting canary tenants to the next epoch precision tier.

| Check ID | Metric | Threshold | Action on Breach |
| --- | --- | --- | --- |
| `CHK-20-A` | Replication lag | `< 50 ms` | Halt canary promotion |
| `CHK-20-B` | Quorum ack ratio | `>= 99.99%` | Drain shard router |
| `CHK-20-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |

## 3. Canary Cohort Parameters

| Cohort | Wire Version | Epoch Unit | Max Drift | Quorum Size | Scope |
| --- | --- | --- | --- | --- | --- |
| `legacy-default` | `v2` | `sec` | `30` | `2` | `GLOBAL` |
| `canary-v3` | `v2` | `sec` | `30` | `2` | `GLOBAL` |

## 4. Literal Patch & Conflict Template

Operators auditing raw diffs must verify the literal marker block below:

```text
<<<<<<< MATCH
wire_version = "v2"
epoch_unit = "sec"
quorum_required = 2
=======
wire_version = "v3"
epoch_unit = "sec"
quorum_required = 2
>>>>>>> REPLACE
```

