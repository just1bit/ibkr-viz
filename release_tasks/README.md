# Release tasks

Release tasks are manually triggered production operations. Each task directory provides a `run.sh` entrypoint:

```text
release_tasks/
  task-name/
    run.sh
    requirements.txt
    ...
```

## Available tasks

| Task directory | Purpose | Write behavior |
| --- | --- | --- |
| `xml-native-values` | Backfill `positions.xml_percent_of_nav` for every stored snapshot and `accounts.previous_net_liquidation` for each user's latest snapshot. | Downloads and validates all canonical XML inputs before applying verified updates in one database transaction. |
| `daily-pnl-contributions` | Create `daily_pnl_contributions` and backfill named, non-zero MTM contributions for every stored snapshot. | Prepares contribution values from canonical XML, replaces each snapshot's contribution rows and verifies row counts in one database transaction. |

Both tasks use the canonical object key `{S3_PREFIX}{user_id}/{report_date}.xml` and validate the XML report date against the database snapshot date.

The `Run release task` GitHub Actions workflow receives a code ref and `task_directory`, authenticates to Azure and executes the entrypoint serially.

Each task directory owns its Python dependencies, environment discovery, source validation, transaction and post-write verification.
