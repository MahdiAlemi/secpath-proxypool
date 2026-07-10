# Monitor lifecycle

Phase 2 replaces PID-only monitor control with a process-safe lifecycle. This document describes local behavior; it does not authorize deployment or production service changes.

## States

A monitor profile can expose these runtime states:

- `idle`: configured but not started.
- `starting`: a start reservation exists while the process is launching.
- `running`: the claimed monitor process is alive and its command line matches the monitor ID.
- `paused`: the current session stopped cooperatively and retains tested-proxy records for resume.
- `completed`: every proxy in the session was processed.
- `stopped`: the operator stopped the process; progress remains visible, but the next Start begins a fresh session.
- `failed`: the worker or result processor failed before the session completed.
- `interrupted`: the registry claimed a running PID, but no matching process remained during reconciliation.

## Duplicate-start prevention

Starting a profile creates a short-lived reservation under:

```text
.runtime/monitors/
```

The child process must activate that reservation using its start token. A second Start request, a duplicate service launch, or a manual duplicate process is rejected while a valid reservation or process claim exists.

PID existence alone is not trusted. A running process must also:

1. have the expected creation timestamp when one is recorded; and
2. contain the exact `--monitor-id <id>` argument in its command line.

This prevents an unrelated process from being controlled after operating-system PID reuse.

## Stop and pause

Stop and Pause write an explicit control request and send `SIGTERM`. The monitor's mutable stop flag is observed by the application, runner, workers, and probe loop. The process is allowed a bounded grace period to finish its current unit of work and persist state. A kill fallback is used only when the process does not exit within the grace period.

Pause retains:

- `monitor_sessions` counts;
- `monitor_tested` rows;
- the current progress JSON.

Resume excludes already-tested proxy IDs and continues the same session. Partial probe attempts are not converted into failures; an interrupted proxy is retried as a complete unit after resume.

Stop retains the final progress snapshot for inspection. A later Start intentionally clears the previous session and starts fresh.

## Progress consistency

The authoritative session counters are persisted after every completed proxy. Progress JSON writes are atomic and throttled. Final progress never forces `tested` to equal `total`; completion is reported only when the actual tested count reaches the session total.

Detailed final status counts are calculated from proxies linked through `monitor_tested`, not by reapplying the original status filter after statuses have changed.

## Recurring modes

`infinite` and `restart` execute complete monitor cycles separated by the configured interval. `custom` uses an hour interval. `schedule` supports:

- `daily`
- `weekdays`
- `weekends`
- comma-separated day names such as `mon,wed,fri`

All waits are interruptible, so Stop and Pause do not wait for the next interval or scheduled time.

## systemd profiles

A profile with `create_service=yes` is started either by systemd or by a direct subprocess, never both. Service creation and removal require the dashboard process to have root privileges. The service uses `SIGTERM`, a bounded stop timeout, `NoNewPrivileges`, and `PrivateTmp`.

Stopping a service-backed monitor stops the service but keeps its service definition. `Remove Service` performs the separate disable-and-delete action.

Creating, starting, stopping, or removing a local system service is an operator action from the dashboard. Applying this overlay itself does not run systemd, deploy the application, or restart any service.

## Runtime cleanup

Normal cleanup leaves monitor state intact:

```bash
bash scripts/clean_runtime.sh
```

Intentional state cleanup also removes lifecycle claims, control files, registry locks, and progress snapshots:

```bash
bash scripts/clean_runtime.sh --include-state
```
