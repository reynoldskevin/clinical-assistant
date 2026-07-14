#!/usr/bin/env bash
#
# Install the sidecar eval-gate git hooks into this clone's .git/hooks.
# Idempotent: re-run any time. Refuses to clobber a foreign hook unless --force.
#
set -euo pipefail

force=0
[ "${1:-}" = "--force" ] && force=1

repo_root="$(git rev-parse --show-toplevel)"
src_dir="$repo_root/sidecar/hooks"

hooks_path="$(git config --get core.hooksPath || true)"
if [ -n "$hooks_path" ]; then
    case "$hooks_path" in
        /*) dest_dir="$hooks_path" ;;
        *)  dest_dir="$repo_root/$hooks_path" ;;
    esac
else
    dest_dir="$repo_root/.git/hooks"
fi
mkdir -p "$dest_dir"

marker="sidecar/hooks/install.sh"
for hook in pre-push; do
    src="$src_dir/$hook"
    dest="$dest_dir/$hook"
    if [ -e "$dest" ] && [ "$force" -ne 1 ] \
        && ! grep -q "$marker" "$dest" 2>/dev/null; then
        echo "install: refusing to overwrite existing $dest (use --force)" >&2
        exit 1
    fi
    cp "$src" "$dest"
    chmod +x "$dest"
    echo "install: $hook -> $dest"
done
