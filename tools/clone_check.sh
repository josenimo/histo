#!/usr/bin/env bash
#
# Run the pipeline from a fresh clone, not from the working tree.
#
# Why this exists: `nextflow run .` reads the files on disk, which include
# everything uncommitted. Git's record can be missing pieces and every stub run
# still passes. That happened once already -- a bare `local/` in .gitignore also
# matched `modules/local/`, so a new module was silently omitted from its own
# commit and HEAD carried an `include` pointing at nothing. Nothing local caught
# it, because nothing local was wrong.
#
# A clone sees only what is committed. Run this before opening a PR.
#
# Usage:
#   tools/clone_check.sh                      # default: -profile laptop,test
#   tools/clone_check.sh laptop,test_cellpose
#   tools/clone_check.sh laptop -params-file /abs/path/params.yml
#
# Any arguments after the profile are passed through to `nextflow run`. Use
# absolute paths for anything outside the repo: the run happens in the clone.

set -euo pipefail

CLONE_DIR=/tmp/histo-clone-check
OUT_DIR=/tmp/histo-clone-out

PROFILE="${1:-laptop,test}"
shift || true

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Paths are hardcoded above rather than taken from the environment, but guard
# anyway: an empty variable would turn the rm below into something catastrophic.
for d in "$CLONE_DIR" "$OUT_DIR"; do
    case "$d" in
        /tmp/*) ;;
        *)
            echo "refusing to remove '$d': not under /tmp" >&2
            exit 1
            ;;
    esac
done

cd "$REPO_ROOT"

# Check pass-through file arguments before doing any work. Without this, a typo
# in a path fails inside the clone and gets reported as "the committed state does
# not run", which sends you looking for a problem that is not there.
prev=""
for arg in "$@"; do
    case "$prev" in
        -params-file | -c | -config)
            # Relative paths are rejected even when they exist. That is the point:
            # a path that resolves here will resolve to something different, or to
            # nothing, inside the clone. Existing-but-wrong is the dangerous case.
            case "$arg" in
                /*) ;;
                *)
                    echo "$prev: needs an absolute path, got: $arg" >&2
                    echo "  The run happens inside the clone, so a relative path either" >&2
                    echo "  fails there or silently resolves to a different file." >&2
                    echo "  Try: $prev $REPO_ROOT/$arg" >&2
                    exit 2
                    ;;
            esac
            if [ ! -e "$arg" ]; then
                echo "$prev: no such file: $arg" >&2
                exit 2
            fi
            ;;
    esac
    prev="$arg"
done

echo "repo    : $REPO_ROOT"
echo "branch  : $(git rev-parse --abbrev-ref HEAD)"
echo "commit  : $(git rev-parse --short HEAD)"
echo "profile : $PROFILE"
echo

# `git status --porcelain` rather than `git diff-index`: diff-index compares
# against cached stat information and reports the whole tree as modified when
# that information is stale, which happens on network and container-mounted
# filesystems. status refreshes the index first.
porcelain="$(git status --porcelain)"
modified="$(printf '%s\n' "$porcelain" | grep -v '^??' | sed '/^$/d' || true)"
untracked="$(printf '%s\n' "$porcelain" | grep '^??' | sed 's/^?? //' || true)"

# Not a failure, but the single most important thing to know while reading the
# result: these changes are NOT in the clone, so this run does not test them.
if [ -n "$modified" ]; then
    echo "WARNING: uncommitted changes; the clone does not contain them:"
    printf '%s\n' "$modified" | sed 's/^/  /'
    echo
fi

if [ -n "$untracked" ]; then
    echo "WARNING: untracked files; the clone does not contain them either."
    echo "         If one of these is a module or script the pipeline needs,"
    echo "         that is exactly the failure this check exists to find:"
    printf '%s\n' "$untracked" | sed 's/^/  /'
    echo
fi

echo "removing $CLONE_DIR and $OUT_DIR"
rm -rf "$CLONE_DIR" "$OUT_DIR"

echo "cloning committed state"
git clone --quiet . "$CLONE_DIR"

echo "running stub"
echo
cd "$CLONE_DIR"
if nextflow run . -profile "$PROFILE" -stub --outdir "$OUT_DIR" "$@"; then
    echo
    echo "PASS: the committed state runs. Results in $OUT_DIR"
else
    status=$?
    echo
    echo "FAIL: the committed state does not run, though your working tree may."
    echo "      Compare against the warnings above: something the pipeline needs"
    echo "      is probably uncommitted or ignored."
    echo "      Clone kept at $CLONE_DIR for inspection."
    exit "$status"
fi
