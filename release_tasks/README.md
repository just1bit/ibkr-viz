# Release tasks

Each direct child directory is one independently executable release task and
must provide a `run.sh` entrypoint:

```text
release_tasks/
  requirement-name/
    run.sh
    ...task-owned scripts and dependencies
```

To execute a task, open the `Run release task` GitHub Actions workflow, select
the intended code ref, and enter `requirement-name` as `task_directory`. The
runner validates the directory name and invokes its entrypoint. Adding a future
task does not require a workflow change.

Tasks execute on every manual trigger. There is intentionally no custom task
history table, completion marker, or skip logic. A task that may be retried
must implement safe repeat behavior inside its own directory.
