#!/usr/bin/env bash
set -euo pipefail

task_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "${POSTGRES_URL:-}" || -z "${S3_BUCKET:-}" ]]; then
  webapp_name="${AZURE_WEBAPP_NAME:-ibkr-viz}"
  resource_group="$(
    az webapp list \
      --query "[?name=='$webapp_name'].resourceGroup | [0]" \
      --output tsv
  )"
  if [[ -z "$resource_group" ]]; then
    echo "Azure Web App not found: $webapp_name"
    exit 1
  fi

  while IFS=$'\t' read -r setting_name setting_value; do
    normalized_name="$(
      printf '%s' "$setting_name" | tr '[:lower:]' '[:upper:]'
    )"
    case "$normalized_name" in
      POSTGRES_URL|S3_BUCKET|S3_ENDPOINT|S3_REGION|S3_ACCESS_KEY|S3_SECRET_KEY|S3_PREFIX|S3_CONNECT_TIMEOUT|S3_READ_TIMEOUT|S3_TOTAL_MAX_ATTEMPTS)
        export "$normalized_name=$setting_value"
        ;;
    esac
  done < <(
    az webapp config appsettings list \
      --resource-group "$resource_group" \
      --name "$webapp_name" \
      --query '[].[name,value]' \
      --output tsv
  )
fi

if [[ -z "${POSTGRES_URL:-}" || -z "${S3_BUCKET:-}" ]]; then
  echo "Required database or S3 application settings are missing"
  exit 1
fi

python3 -m pip install \
  --disable-pip-version-check \
  --requirement "$task_dir/requirements.txt"
python3 "$task_dir/task.py"
