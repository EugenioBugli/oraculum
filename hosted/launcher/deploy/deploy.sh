#!/bin/bash
# Pull-based deploy of the oraculum launcher on the droplet (owner's choice 2026-10-19: automatic from the default
# branch). The droplet pulls the private repo with a READ-ONLY deploy key (/opt/oraculum-launcher/deploy_key, added
# under the repo's Settings -> Deploy keys); no secret is stored in GitHub. Secrets stay in /opt/oraculum-launcher/
# (modal.env, github-oauth.env, cookie.env; mode 600). Run by oraculum-deploy.timer every 5 minutes.
#
#   /opt/oraculum-launcher/deploy.sh          # deploy if origin/$BRANCH moved
#   FORCE=1 /opt/oraculum-launcher/deploy.sh  # redeploy the current commit
#
# The session image (Modal) is not rebuilt here: it needs the private spqrbooster2026. Its id lives in
# /opt/oraculum-launcher/image_id (written by the person who builds it with hosted/modal_session.py start).
set -euo pipefail
cd /opt/oraculum-launcher
REPO=${REPO:-git@github.com:EmanueleMusumeci/robocup_ui.git}
BRANCH=${BRANCH:-main}
[ -f deploy_key ] && export GIT_SSH_COMMAND="ssh -i /opt/oraculum-launcher/deploy_key -o IdentitiesOnly=yes"
log() { echo "$(date -u +%FT%TZ) $*" | tee -a deploy.log; }

[ -d repo/.git ] || git clone -q --depth 50 -b "$BRANCH" "$REPO" repo
git -C repo fetch -q --depth 50 origin "$BRANCH"
NEW=$(git -C repo rev-parse --short=12 "origin/$BRANCH")
OLD=$(cat deployed 2>/dev/null || true)
[ "$NEW" = "$OLD" ] && [ -z "${FORCE:-}" ] && exit 0
git -C repo reset -q --hard "origin/$BRANCH"
[ -f repo/hosted/launcher/Dockerfile ] || { log "skip $NEW: no hosted/launcher in this commit"; exit 0; }

log "deploying $NEW (was ${OLD:-none})"
docker build -q -t "oraculum-launcher:$NEW" repo/hosted/launcher >/dev/null
run() {  # $1 image tag
    docker rm -f oraculum-launcher >/dev/null 2>&1 || true
    docker run -d --name oraculum-launcher --restart unless-stopped --network host --env-file modal.env \
        -e ORACULUM_IMAGE_ID="$(cat image_id)" -v /opt/oraculum-launcher/data:/data "oraculum-launcher:$1" >/dev/null
}
healthy() {  # the launcher answers a signed-in request within 30 s
    for _ in $(seq 15); do
        sleep 2
        curl -fs -H "X-Auth-Request-User: deploy-check" http://127.0.0.1:18100/api/state >/dev/null && return 0
    done
    return 1
}
run "$NEW"
if healthy; then
    echo "$NEW" > deployed
    log "deployed $NEW"
else
    log "FAILED $NEW: rolling back to ${OLD:-nothing}"
    [ -n "$OLD" ] && run "$OLD" && healthy && log "rolled back to $OLD"
    exit 1
fi
# keep the last 3 launcher images
docker images "oraculum-launcher" --format '{{.Tag}} {{.CreatedAt}}' | sort -k2 -r | awk 'NR>3 {print $1}' \
    | while read -r tag; do [ "$tag" != "$NEW" ] && docker rmi -f "oraculum-launcher:$tag" >/dev/null 2>&1 || true; done
