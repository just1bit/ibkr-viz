# Release tasks

Release tasks are manually triggered production operations. Each task directory provides a `run.sh` entrypoint:

```text
release_tasks/
  task-name/
    run.sh
    requirements.txt
    ...
```

The `Run release task` GitHub Actions workflow receives a code ref and `task_directory`, authenticates to Azure and executes the entrypoint serially.

Each task owns its dependencies, environment discovery and repeatable or transactional execution.
