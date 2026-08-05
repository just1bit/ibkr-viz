# Release tasks

Release tasks are manually triggered, one-time production operations that remain separate from application startup. Each direct child directory is self-contained and must expose a `run.sh` entrypoint:

```text
release_tasks/
  task-name/
    run.sh
    requirements.txt
    ...
```

To run one, open the `Run release task` GitHub Actions workflow, select the code ref, and enter the directory name as `task_directory`. The workflow accepts only a single safe path segment, verifies `release_tasks/<name>/run.sh`, authenticates to Azure with the repository's scoped identity, and executes the entrypoint. Production release tasks do not run concurrently.

Every manual trigger executes the task. There is no shared migration table, completion marker or automatic skip behavior, so each task must either be safely repeatable or fail before making partial changes. Dependencies and environment discovery belong inside the task directory; adding a task does not require a workflow change.
