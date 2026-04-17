#!/bin/bash
# Fails if any gh-aw workflow spec (.md) is newer than its compiled lock file (.lock.yml),
# indicating the lock file needs to be regenerated with: gh aw compile -j <file>
stale=0
for md in "$@"; do
  lock="${md%.md}.lock.yml"
  if [ ! -f "$lock" ]; then
    echo "Missing lock file for $md — run: gh aw compile -j $md"
    stale=1
  elif [ "$md" -nt "$lock" ]; then
    echo "Lock file is stale for $md — run: gh aw compile -j $md"
    stale=1
  fi
done
exit $stale
