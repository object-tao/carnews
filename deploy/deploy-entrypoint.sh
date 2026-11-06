#!/bin/sh
# This is the forced SSH command for the dedicated, key-only deployment account.
set -eu
case "${SSH_ORIGINAL_COMMAND:-}" in
    'deploy '*) commit=${SSH_ORIGINAL_COMMAND#deploy } ;;
    *) echo 'Only a versioned Kunteng release is permitted' >&2; exit 1 ;;
esac
case "$commit" in ''|*[!a-f0-9]*) exit 1 ;; esac
test "${#commit}" -eq 40
exec sudo -n /usr/local/sbin/kunteng-release "$commit"
