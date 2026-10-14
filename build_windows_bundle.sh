#!/usr/bin/env bash
# Copyright 2026 Platform9 Systems, Inc.
#
# Build an offline Windows bundle of pcd_vm_inventory.py: a standalone
# Python, every dependency preinstalled, and a run.cmd launcher, zipped into
# dist/. The Windows machine needs no internet access and no Python install.
#
# Runs on Linux or macOS with uv, curl, and zip. Downloads come from
# python-build-standalone and PyPI on the build machine only; dependency
# wheels are checked against hashes locked at build time.
#
#   ./build_windows_bundle.sh
#   -> dist/pcd-vm-inventory-windows-x64.zip
set -euo pipefail

PY_VERSION=3.12.15
PY_BUILD=20261009
PY_ARCHIVE="cpython-${PY_VERSION}+${PY_BUILD}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
PY_RELEASE="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_BUILD}"
PLATFORM=x86_64-pc-windows-msvc

here="$(cd "$(dirname "$0")" && pwd)"
script="$here/pcd_vm_inventory.py"
out="$here/dist/pcd-vm-inventory-windows-x64.zip"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
bundle="$work/pcd-vm-inventory"
mkdir -p "$bundle" "$here/dist"

echo "Downloading Python ${PY_VERSION} for Windows"
curl -fsSL -o "$work/$PY_ARCHIVE" "$PY_RELEASE/${PY_ARCHIVE//+/%2B}"
curl -fsSL -o "$work/SHA256SUMS" "$PY_RELEASE/SHA256SUMS"
(cd "$work" && grep " ${PY_ARCHIVE}\$" SHA256SUMS | sha256sum -c -)
tar -xzf "$work/$PY_ARCHIVE" -C "$bundle"   # creates $bundle/python/

echo "Locking dependencies for Windows"
# Read the pinned dependencies from the script's inline metadata.
sed -n '/^# dependencies = \[/,/^# \]/p' "$script" \
    | grep -o '"[^"]*"' | tr -d '"' > "$work/requirements.in"
uv pip compile "$work/requirements.in" -o "$work/requirements.txt" -q \
    --python-platform "$PLATFORM" --python-version "${PY_VERSION%.*}" \
    --only-binary :all: --generate-hashes --no-header

echo "Installing dependencies"
uv pip install -q --target "$bundle/python/Lib/site-packages" \
    --python-platform "$PLATFORM" --python-version "${PY_VERSION%.*}" \
    --only-binary :all: --require-hashes -r "$work/requirements.txt"
cp "$work/requirements.txt" "$bundle/requirements-windows.txt"

cp "$script" "$bundle/"
printf '@"%%~dp0python\\python.exe" "%%~dp0pcd_vm_inventory.py" %%*\r\n' > "$bundle/run.cmd"

rm -f "$out"
(cd "$work" && zip -qr -9 "$out" pcd-vm-inventory)
echo "Wrote $out ($(du -h "$out" | cut -f1))"
