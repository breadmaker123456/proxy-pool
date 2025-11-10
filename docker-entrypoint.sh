#!/usr/bin/env bash
set -euo pipefail

cd /app

if [ $# -eq 0 ]; then
  set -- scheduler
fi

case "$1" in
  collector)
    shift
    exec python run_collector.py "$@"
    ;;
  scheduler)
    shift
    exec python scheduler.py "$@"
    ;;
  subscription)
    shift
    exec python subscription_scheduler.py "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
