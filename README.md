# Trace — Forensic Data Acquisition & Case Engine

Trace is an air-gap-friendly, crash-resilient forensic acquisition and case management engine.

## Quickstart

### Running the Interactive Shell
```bash
trace
```

### Direct CLI Commands
```bash
trace case create --number "2026-CR-0001" --title "Digital Drive Acquisition" --examiner "Investigator A"
trace case list
trace case show 2026-CR-0001
trace case edit 2026-CR-0001 --notes "Preliminary findings recorded"
trace case close 2026-CR-0001
trace case delete 2026-CR-0001
```
