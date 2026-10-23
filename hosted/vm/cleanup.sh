#!/bin/bash
# Remove what a previous circus run leaves behind. circus stops on any of these with a dialog box on the invisible
# display and hangs: a robot container with the same name, the network CIRCUS_network, the shared-memory folder.
ids=$(docker ps -aq --filter name=CIRCUS_)
[ -n "$ids" ] && docker rm -f $ids >/dev/null
docker network rm CIRCUS_network >/dev/null 2>&1
rm -rf /dev/shm/circus_ipc
exit 0
