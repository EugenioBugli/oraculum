"""Authenticated operator jobs. Browser input never contains commands or paths."""
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
import uuid

from artifact_stage import stage
from wired_deploy_plan import plan as deploy_plan


ROLES = {"build": "software", "stage": "software", "deploy": "deploy", "rollback": "deploy",
         "service-start": "service", "service-stop": "service", "service-restart": "service",
         "network-apply": "network", "network-rollback": "network", "simulate": "simulation"}
SUPPORTED = {"deploy", "rollback", "service-start", "service-stop", "service-restart"}


class JobError(ValueError):
    pass


class OperationJobs:
    def __init__(self, inspector, artifact_root, config, *, runner=None, operators=None):
        self.inspector = inspector
        self.artifacts = Path(artifact_root)
        self.config = config.get("operations", {})
        self.operators = operators if operators is not None else json.loads(os.environ.get("ORACULUM_OPERATORS", "{}"))
        for name, operator in self.operators.items():
            if not re.fullmatch(r"[\w-]{1,40}", name) or len(operator.get("token", "")) < 24:
                raise ValueError("Operator names and tokens must be valid (tokens at least 24 characters)")
        self.root = self.artifacts.parent / ".operation-jobs"
        self.lock = threading.RLock()
        self.jobs, self.previews, self.keys, self.cancelled = {}, {}, {}, {}
        self.approvals = {}
        self.runner = runner or self._run
        self.active = None
        if self.root.is_dir():
            for path in sorted(self.root.glob("*.json"))[-500:]:
                if path.is_symlink() or not re.fullmatch(r"[a-f0-9]{32}\.json", path.name):
                    continue
                try:
                    job = json.loads(path.read_text())
                    if job["id"] != path.stem or job["owner"] not in self.operators:
                        continue
                    if job["status"] in ("queued", "running"):
                        job.update(status="interrupted", phase="unknown", error="Gateway restarted; inspect the remote state before retrying")
                    self.jobs[job["id"]] = job
                    self.cancelled[job["id"]] = threading.Event()
                    if job.get("request_key"):
                        self.keys[job["owner"], job["request_key"]] = job["id"]
                except (ValueError, KeyError, TypeError):
                    continue

    def identity(self, token):
        for name, operator in self.operators.items():
            if token and hmac.compare_digest(token, operator["token"]):
                return name
        raise PermissionError("An operator token is required for this workflow")

    def capabilities(self, owner):
        operator = self.operators[owner]
        return {"operator": owner, "roles": operator.get("roles", []),
                "targets": operator.get("targets", []), "simulator": bool(self.config.get("simulator")),
                "network_profiles": [{"id": p["id"], "label": p.get("label", p["id"]), "target": p["target"]}
                                     for p in self.config.get("network_profiles", [])]}

    def _target(self, identifier):
        if identifier == "gateway":
            return {"id": "gateway", "gateway_connected": True, "ip": None}
        target = next((t for t in self.inspector.inventory()["targets"] if t["id"] == identifier), None)
        if not target:
            raise JobError("Unknown configured robot")
        return target

    def _authorize(self, owner, action, target):
        operator = self.operators[owner]
        if action not in ROLES or ROLES[action] not in operator.get("roles", []):
            raise PermissionError("Operator is not authorized for this action")
        if action != "simulate" and target not in operator.get("targets", []):
            raise PermissionError("Operator is not authorized for this robot")
        if target == "gateway" and action not in ("network-apply", "network-rollback"):
            raise PermissionError("Only configured network profiles are supported for the gateway host")

    def preview(self, owner, body):
        action, identifier = body.get("action"), body.get("target")
        self._authorize(owner, action, identifier)
        spec = {"action": action, "target": identifier}
        target = self._target(identifier) if action != "simulate" else None
        steps = []
        if action in ("build", "stage"):
            from artifact_preview import _git, _source_dirty
            spec["source_commit"] = _git(target["repo"], "rev-parse", "HEAD")
            if not spec["source_commit"] or _source_dirty(target["repo"]):
                raise JobError("Choose a clean, committed checkout before previewing software work")
            profile = body.get("profile", "practice")
            if profile not in ("practice", "match"):
                raise JobError("Unknown practice/match profile")
            spec["profile"] = profile
            if action == "build" and not self.config.get("build_argv"):
                raise JobError("Configure operations.build_argv before building")
            steps = ["Source commit: " + spec["source_commit"], "Build the pinned source" if action == "build" else "Verify and stage immutable binary/config hashes"]
        elif action == "deploy":
            spec["artifact"] = str(body.get("artifact", ""))
            review = deploy_plan(self.artifacts, spec["artifact"], target)
            if not target["gateway_connected"]:
                raise JobError("The configured Ethernet gateway address is not active")
            self._layout(identifier)
            steps = review["phases"]
        elif action in ("rollback", "network-rollback"):
            source = self.get(owner, str(body.get("job", "")))
            expected = "deploy" if action == "rollback" else "network-apply"
            if source["spec"]["action"] != expected or source["spec"]["target"] != identifier or source["status"] != "succeeded":
                raise JobError("Choose a successful operation for this robot to roll back")
            spec["job"] = source["id"]
            steps = ["Restore the selected operation's backup", "Verify service or network state"]
        elif action == "network-apply":
            profile = next((p for p in self.config.get("network_profiles", [])
                            if p.get("id") == body.get("profile") and p.get("target") == identifier), None)
            if not profile or not re.fullmatch(r"[0-9a-fA-F-]{36}", profile.get("uuid", "")):
                raise JobError("Choose an existing, configured NetworkManager profile")
            if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,32}", profile.get("interface", "")):
                raise JobError("Network profile interface is not configured")
            spec["profile"] = profile["id"]
            steps = ["Record current connection UUID", "Activate the configured profile with an automatic recovery timer",
                     "Verify interface address and SSH; cancel recovery only after verification"]
        elif action == "simulate":
            from simulation_jobs import normalize
            if not self.config.get("simulator"):
                raise JobError("No isolated simulator image configured on this gateway")
            spec["scenario"] = normalize(body.get("scenario"))
            steps = ["Validate ghost-only scenario", "Write scene/field/config into a private session directory",
                     "Start the configured Docker image with network disabled", "Report process state until stopped"]
        else:
            self._layout(identifier)
            steps = ["Verify SSH service identity", action.replace("-", " "), "Read observed service state"]
        token = uuid.uuid4().hex
        with self.lock:
            self.previews = {k: v for k, v in self.previews.items() if v["expires"] > time.time()}
            if len(self.previews) >= 64:
                raise JobError("Too many pending previews; wait for them to expire")
            self.previews[token] = {"owner": owner, "spec": spec, "expires": time.time() + 120}
        return {"preview": token, "spec": spec, "steps": steps, "expires_in": 120,
                "support_required": action in SUPPORTED, "confirmation": identifier or "simulation"}

    def submit(self, owner, body):
        key = body.get("key", "")
        if not isinstance(key, str) or not re.fullmatch(r"[\w-]{8,80}", key):
            raise JobError("A unique request key is required")
        with self.lock:
            if (owner, key) in self.keys:
                return self.get(owner, self.keys[owner, key])
            preview = self.previews.get(body.get("preview"))
            if not preview or preview["owner"] != owner or preview["expires"] < time.time():
                raise JobError("Preview expired; review again")
            spec = preview["spec"]
            self._authorize(owner, spec["action"], spec["target"])
            if body.get("confirm") != (spec["target"] or "simulation"):
                raise JobError("Confirm the exact target")
            if spec["action"] in SUPPORTED and body.get("supported") is not True:
                raise JobError("Confirm that the robot is physically supported for this operation")
            if self.active:
                raise JobError("Another operation is running; wait or cancel it first")
            identifier = uuid.uuid4().hex
            job = {"id": identifier, "owner": owner, "spec": copy.deepcopy(spec), "status": "queued",
                   "phase": "queued", "created": time.time(), "logs": [], "result": None, "error": None,
                   "request_key": key}
            self._save(job)
            self.jobs[identifier] = job
            self.keys[owner, key] = identifier
            self.cancelled[identifier] = threading.Event()
            self.approvals[identifier] = threading.Event()
            self.active = identifier
            del self.previews[body["preview"]]
            threading.Thread(target=self._worker, args=(identifier,), daemon=True).start()
            return copy.deepcopy(job)

    def get(self, owner, identifier):
        with self.lock:
            job = self.jobs.get(identifier)
            if not job or job["owner"] != owner:
                raise JobError("Unknown operation")
            return copy.deepcopy(job)

    def list(self, owner):
        with self.lock:
            return [copy.deepcopy(j) for j in reversed(list(self.jobs.values())) if j["owner"] == owner][:50]

    def cancel(self, owner, identifier):
        with self.lock:
            job = self.get(owner, identifier)
            if job["phase"] == "activating":
                raise JobError("Activation is atomic; wait for verification or automatic rollback")
            self.cancelled[identifier].set()
            return job

    def confirm_network(self, owner, identifier):
        with self.lock:
            job = self.get(owner, identifier)
            if job["phase"] != "awaiting network confirmation" or job["spec"]["target"] != "gateway":
                raise JobError("No gateway network change is awaiting confirmation")
            self.approvals[identifier].set()
            return job

    def busy_ip(self, ip):
        with self.lock:
            if not self.active:
                return False
            spec = self.jobs[self.active]["spec"]
            return spec["action"] not in ("build", "stage", "simulate") and self.inspector.targets.get(spec["target"], {}).get("ip") == ip

    def _save(self, job):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.root / (job["id"] + ".json")
        temporary = path.with_suffix(".tmp")
        with open(temporary, "w", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
            json.dump(job, stream, indent=2)
        os.replace(temporary, path)

    def _log(self, identifier, message):
        with self.lock:
            # Keep logs bounded and strip configured operator secrets if a tool echoes one.
            message = self._redact(message)
            self.jobs[identifier]["logs"] = (self.jobs[identifier]["logs"] + [message[-2000:]])[-80:]

    def _redact(self, text):
        for operator in self.operators.values():
            text = text.replace(operator["token"], "[redacted]")
        gateway = os.environ.get("ORACULUM_ACCESS_TOKEN")
        return text.replace(gateway, "[redacted]") if gateway else text

    def _phase(self, identifier, phase):
        with self.lock:
            if self.cancelled[identifier].is_set():
                raise InterruptedError("Operation cancelled before activation")
            self.jobs[identifier]["phase"] = phase

    def _worker(self, identifier):
        job = self.jobs[identifier]
        try:
            job["status"] = "running"
            self._phase(identifier, "preflight")
            result = self._execute(identifier, job["spec"])
            job.update(status="cancelled" if self.cancelled[identifier].is_set() else "succeeded", result=result)
        except InterruptedError as exc:
            job.update(status="cancelled", error=str(exc))
        except Exception as exc:
            job.update(status="failed", error=self._redact(str(exc))[:400])
        finally:
            with self.lock:
                job["finished"] = time.time()
                job["phase"] = "finished"
                self.active = None
                self._save(job)

    def _run(self, identifier, argv, *, cwd=None, input=None, timeout=120, cancellable=True):
        """Process group cancellation; output is drained to disk rather than unbounded RAM."""
        import tempfile
        with tempfile.TemporaryFile() as output:
            proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                                    stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
                                    env={k:v for k,v in os.environ.items() if k not in ("ORACULUM_OPERATORS", "ORACULUM_ACCESS_TOKEN")})
            if input is not None:
                proc.stdin.write(input.encode()); proc.stdin.close()
            started, offset = time.monotonic(), 0
            while proc.poll() is None:
                if os.fstat(output.fileno()).st_size > 8 * 1024 * 1024:
                    os.killpg(proc.pid, signal.SIGKILL); proc.wait()
                    raise JobError("Process output exceeded 8 MiB; stopped")
                if time.monotonic() - started > timeout or (cancellable and self.cancelled[identifier].is_set() and self.jobs[identifier]["phase"] != "activating"):
                    os.killpg(proc.pid, signal.SIGTERM)
                    try: proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL); proc.wait()
                    if cancellable and self.cancelled[identifier].is_set():
                        raise InterruptedError("Operation cancelled")
                    raise JobError("Process timed out; verify remote state before retrying")
                output.seek(offset)
                chunk = output.read(8192)
                offset += len(chunk)
                if chunk: self._log(identifier, chunk.decode(errors="replace"))
                time.sleep(.1)
            output.seek(0, 2); size = output.tell()
            output.seek(max(0, size - 16000))
            text = self._redact(output.read().decode(errors="replace"))
            self._log(identifier, text)
            if proc.returncode:
                raise JobError(f"Process exited {proc.returncode}: {text[-600:]}")
            return text

    def _layout(self, target):
        layout = self.config.get("deployments", {}).get(target)
        if not layout:
            raise JobError("Verify and configure the robot installation paths before activation")
        for key in ("binary", "config"):
            value = layout.get(key, "")
            if not re.fullmatch(r"/home/[a-zA-Z0-9_./-]+", value) or ".." in Path(value).parts:
                raise JobError("Invalid configured installation path")
        services = layout.get("services", [self.inspector.targets[target]["service"]])
        if not isinstance(services, list) or not services or any(not isinstance(s, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,63}", s) for s in services):
            raise JobError("Invalid installation service list")
        if self.inspector.targets[target]["service"] not in services:
            raise JobError("Installation services must include the configured primary service")
        return layout

    def _ssh(self, identifier, target, script, timeout=120):
        if target["id"] == "gateway":
            return self.runner(identifier, ["bash", "-se"], input=script, timeout=timeout)
        return self.runner(identifier, ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                                      "-o", "ConnectTimeout=5", target["user"] + "@" + target["ip"], "bash", "-se"],
                           input=script, timeout=timeout)

    def _execute(self, identifier, spec):
        action = spec["action"]
        if action == "simulate":
            from simulation_jobs import run_session
            return run_session(self, identifier, spec["scenario"])
        target = self._target(spec["target"])
        if action in ("build", "stage"):
            from artifact_preview import _git
            if _git(target["repo"], "rev-parse", "HEAD") != spec["source_commit"]:
                raise JobError("Source commit changed since preview; review again")
        if action == "stage":
            self._phase(identifier, "staging")
            return stage(target["repo"], target, spec["profile"], self.artifacts)
        if action == "build":
            from artifact_preview import _git, _source_dirty
            if _source_dirty(target["repo"]):
                raise JobError("Build source must be clean and committed")
            commit = _git(target["repo"], "rev-parse", "HEAD")
            self._phase(identifier, "building")
            self.runner(identifier, self.config["build_argv"], cwd=target["repo"], timeout=3600)
            if _git(target["repo"], "rev-parse", "HEAD") != commit or _source_dirty(target["repo"]):
                raise JobError("Source changed during build; discard this result")
            return {"source_commit": commit, "message": "Build exited successfully; preview and stage next"}
        if not target["gateway_connected"]:
            raise JobError("Configured Ethernet address is not active")
        if action.startswith("service-"):
            from wired_activation import identity_script
            verb = action.removeprefix("service-")
            service = target["service"]
            self._ssh(identifier, target, identity_script(target, self._layout(target["id"])))
            self._phase(identifier, "activating")
            observed = self._ssh(identifier, target, f"set -e\nsudo -n systemctl {verb} {service}\n" +
                                 (f'test "$(systemctl show {service} --property=ActiveState --value)" = inactive\n' if verb == "stop" else f"systemctl is-active --quiet {service}\n") +
                                 f"systemctl show {service} --property=ActiveState,SubState,Result\n")
            return {"observed": observed.strip()}
        if action.startswith("network-"):
            from network_jobs import execute
            return execute(self, identifier, target, spec)
        from wired_activation import execute
        return execute(self, identifier, target, spec)
