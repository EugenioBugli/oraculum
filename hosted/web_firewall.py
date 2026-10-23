"""Make ONE session server public on HTTPS: a separate firewall "oraculum-web" (tcp 22, 80, 443) instead of the shared
"oraculum-ssh-only". The shared firewall and the other servers do not change. Port 8080 stays closed: put Caddy (TLS)
in front of the gateway on 443. Run from /DATA/RoboCup/oraculum/hosted:
    python3 web_firewall.py <server id>          # public
    python3 web_firewall.py <server id> --close  # back to ssh only
"""
import sys

import hetzner as h

SID = int(sys.argv[1])
res = [{"type": "server", "server": {"id": SID}}]
by = {f["name"]: f for f in h.call("GET", "/firewalls")["firewalls"]}
if "oraculum-web" not in by:
    rules = [{"direction": "in", "protocol": "tcp", "port": p, "source_ips": ["0.0.0.0/0", "::/0"], "description": d}
             for p, d in (("22", "ssh"), ("80", "acme http-01"), ("443", "https gateway"))]
    by["oraculum-web"] = h.call("POST", "/firewalls", {"name": "oraculum-web", "labels": {"oraculum": "firewall"},
                                                       "rules": rules})["firewall"]
on, off = (by[h.FIREWALL], by["oraculum-web"]) if "--close" in sys.argv else (by["oraculum-web"], by[h.FIREWALL])
h.call("POST", f"/firewalls/{on['id']}/actions/apply_to_resources", {"apply_to": res})
h.call("POST", f"/firewalls/{off['id']}/actions/remove_from_resources", {"remove_from": res})
print(f"server {SID}: firewall {on['name']}")
