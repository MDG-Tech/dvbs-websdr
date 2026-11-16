#!/bin/sh
set -eu
cd "$(dirname "$0")"
export SOAPY_SDR_PLUGIN_PATH="$PWD/native/build/soapy"
export LD_LIBRARY_PATH="$PWD/native/miri/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$PWD/.venv/bin/python" server.py "$@"
