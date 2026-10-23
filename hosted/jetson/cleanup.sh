#!/bin/bash
# Remove what a previous circus run on the Jetson leaves behind (circus hangs on a dialog box if any is left):
# our robot containers, CIRCUS_network, /dev/shm/circus_ipc (its files belong to root: removed from a container).
# Only containers of OUR image are removed; another user's circus run makes this script stop.
others=$(docker ps -a --filter name=CIRCUS_ --format '{{.Names}} {{.Image}}' | grep -v ' oraculum-arm-robot$')
[ -n "$others" ] && { echo "cleanup: CIRCUS_ containers of another image exist, not ours, stopping:" >&2; echo "$others" >&2; exit 1; }
ids=$(docker ps -aq --filter name=CIRCUS_ --filter ancestor=oraculum-arm-robot)
[ -n "$ids" ] && docker rm -f $ids >/dev/null
docker network rm CIRCUS_network >/dev/null 2>&1
[ -e /dev/shm/circus_ipc ] && docker run --rm --network host --entrypoint "" -v /dev/shm:/dev/shm oraculum-arm-robot rm -rf /dev/shm/circus_ipc
exit 0
