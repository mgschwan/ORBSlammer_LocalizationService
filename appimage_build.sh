#!/bin/bash
# Two-phase AppImage build.
#
# appimage-builder's libc integration has three bugs when targeting Noble:
#   1. Patches ELF interpreters to relative paths then removes lib64/ld-linux
#      → AppRun can't find the ld-linux and segfaults
#   2. Leaves a stale older ld-linux in runtime/compat/lib/ from a previous
#      Jammy build, mismatching the Noble libc.so.6
#   3. Patches (corrupts) the bundled libc.so.6 via RPATH tools, causing a
#      segfault in glibc init when the compat layer is used
#
# We fix all three by running the deploy phase, then restoring clean system
# copies of the affected glibc files, then running the package phase.
#
# Usage: ./appimage_build.sh [path_to_appimage_builder]
set -e

APPIMAGE_BUILDER="${1:-/home/developer/Downloads/appimage-builder-x86_64.AppImage}"
APPDIR="AppDir"
GLIBC_LIB="/lib/x86_64-linux-gnu"

cd "$(dirname "$0")"

# Install project libraries, binary and html into AppDir
cmake --install build --prefix "$APPDIR"

# Phase 1: deploy apt packages and patch AppDir
"$APPIMAGE_BUILDER" --skip-appimage --skip-tests

# Fix 1: compat ld-linux version mismatch (appimage-builder may leave a stale
# older ld-linux in runtime/compat/lib/ while Noble provides a newer libc.so.6)
cp "$GLIBC_LIB/ld-linux-x86-64.so.2" \
   "$APPDIR/runtime/compat/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2"

# Fix 2: AppRun resolves APPDIR_LIBC_LINKER_PATH relative to AppDir root, so
# lib64/ld-linux-x86-64.so.2 must exist there (appimage-builder removes it)
cp "$GLIBC_LIB/ld-linux-x86-64.so.2" "$APPDIR/lib64/ld-linux-x86-64.so.2"

# Fix 3: appimage-builder patches the bundled libc.so.6 (RPATH tools corrupt
# it), causing a segfault in glibc init.  Replace with the unmodified system copy.
cp "$GLIBC_LIB/libc.so.6" \
   "$APPDIR/runtime/compat/usr/lib/x86_64-linux-gnu/libc.so.6"

# Phase 2: package the AppImage from the current AppDir state (no re-deploy)
"$APPIMAGE_BUILDER" --skip-build --skip-tests
