"""OS-resource smoke test for Fast-KV cluster manager.
Run away from existing manager/server ports 6381, 7381, 7000.
"""
import os
import pathlib
import re
import resource
import signal
import socket
import subprocess
import sys
import tempfile
import time


def ask(command):
    with socket.create_connection(("127.0.0.1", 7000), timeout=2) as s:
        s.sendall((command + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(32768)
            if not chunk:
                raise AssertionError("connection closed")
            data += chunk
        return data.decode().strip()


def wait_for(check, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (OSError, ValueError):
            pass
        time.sleep(0.05)
    raise AssertionError("condition not reached before timeout")


def proc_pid(status):
    return int(re.search(r"\bpid=(\d+)", status).group(1))


def main(manager, server):
    manager = str(pathlib.Path(manager).resolve())
    server = str(pathlib.Path(server).resolve())
    with tempfile.TemporaryDirectory(prefix="fastkv_os_resources_") as directory:
        env = os.environ.copy()
        env.pop("FASTKV_CGROUP_PARENT", None)
        env.pop("FASTKV_NODE_MEMORY_MAX_BYTES", None)
        env["FASTKV_NOFILE_LIMIT"] = "256"
        with open(pathlib.Path(directory) / "manager.log", "w+") as logfile:
            proc = subprocess.Popen([manager, server, "90", "4096", "1", "1"],
                                    cwd=directory, stdout=logfile,
                                    stderr=subprocess.STDOUT, env=env,
                                    start_new_session=True)
            try:
                wait_for(lambda: ask("PING") == "PONG")
                report = ask("OSSTATS")
                assert "node=6381" in report and "replica=7381" in report, report
                assert report.count("nofile_soft_limit=256") == 2, report
                assert report.count("os_memory_enforced=no") == 2, report
                all_rss = re.findall(r"rss_bytes=(\d+)", report)
                assert len(all_rss) == 2 and all(int(v) > 0 for v in all_rss), report
                if sys.platform.startswith("linux") and hasattr(resource, "prlimit"):
                    actual = resource.prlimit(proc_pid(ask("CLUSTER STATUS")), resource.RLIMIT_NOFILE)
                    assert actual[0] == 256, actual
                print("PASS: OSSTATS shows real process RSS and OS file-descriptor limit")

                assert ask("SET hello world") == "OK"
                oldpid = proc_pid(ask("CLUSTER STATUS"))
                os.kill(oldpid, signal.SIGKILL)
                wait_for(lambda: "promotions=1" in ask("CLUSTER STATUS"))
                assert ask("GET hello") == "world"
                report = ask("OSSTATS")
                assert "node=7381" in report and "replica=6381" in report, report
                assert report.count("nofile_soft_limit=256") == 2
                print("PASS: resource reporting and limits survive primary failover")
            finally:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
    print("ALL OS RESOURCE SMOKE TESTS PASSED")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: test_os_resources.py MANAGER_PATH FASTKV_PATH")
    main(sys.argv[1], sys.argv[2])
