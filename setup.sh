#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
cmake -S vendor/libmirisdr-5 -B native/build/miri -DDETACH_KERNEL_DRIVER=ON -DCMAKE_INSTALL_PREFIX="$PWD/native/miri"
cmake --build native/build/miri -j4
cmake --install native/build/miri
PKG_CONFIG_PATH="$PWD/native/miri/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}" cmake -S vendor/SoapyMiri -B native/build/soapy -DCMAKE_PREFIX_PATH="$PWD/native/miri"
cmake --build native/build/soapy -j4
python3 tools/build_decoder.py
python3 tools/build_decoder.py --s2
python3 tools/fetch_media.py
