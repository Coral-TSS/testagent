#!/bin/sh
# Container entrypoint: "platform" (default), "demo", or any other command.
set -e
cd /app

case "${1:-platform}" in
  platform)
    [ "$#" -gt 0 ] && shift
    if [ "${TESTAGENT_SEED_DEMO:-0}" = "1" ]; then
      # idempotent: creates the demo SUT (model, APIs, people, environment) only once
      python ops/seed_supply_chain.py
    fi
    # migrations run on start; no browser in a container; the demo runs in its own container
    exec testagent --no-browser --no-env-start "$@"
    ;;
  demo)
    [ "$#" -gt 0 ] && shift
    mkdir -p /data
    export SUPPLY_CHAIN_DB="${SUPPLY_CHAIN_DB:-/data/supply_chain.db}"
    exec uvicorn examples.supply_chain.api:create_app --factory --app-dir /app \
      --host 0.0.0.0 --port "${SUPPLY_CHAIN_PORT:-8766}" "$@"
    ;;
  healthcheck)
    exec python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('$2', timeout=4).status == 200 else 1)"
    ;;
  *)
    exec "$@"
    ;;
esac
