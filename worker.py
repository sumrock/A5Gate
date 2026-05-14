#!/usr/bin/env python3
"""
Worker — 定时轮询 Gateway 获取新命令，用指定用户的 login shell 执行后回传结果。
"""

import hashlib
import hmac
import os
import subprocess
import time
import logging
import argparse

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("worker")

DEFAULT_GATEWAY = "http://localhost:8000"
POLL_INTERVAL = 2  # seconds
EXEC_TIMEOUT = 300  # seconds

SHARED_SECRET = os.environ.get("SHARED_SECRET", "")


def auth_headers(method: str, path: str) -> dict:
    if not SHARED_SECRET:
        return {}
    ts = str(int(time.time()))
    payload = f"{ts}\n{method}\n{path}".encode()
    sig = hmac.new(SHARED_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return {"Authorization": f"HMAC-SHA256 {sig}", "X-Timestamp": ts}


def run_as_user(command: str, user: str) -> tuple[str, str, int]:
    """以指定用户的 login shell 执行命令，返回 (stdout, stderr, exit_code)。"""
    if os.geteuid() != 0:
        logger.warning("Worker not running as root, executing directly as current user")
        return run_directly(command)

    if user == "root":
        logger.error("Refusing to execute command as root")
        return "", "root execution is forbidden", -1
    cmd = ["su", "-", user, "-c", command]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=EXEC_TIMEOUT)
        return proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out after {}s".format(EXEC_TIMEOUT), -1


def run_directly(command: str) -> tuple[str, str, int]:
    try:
        proc = subprocess.run(
            ["bash", "-lc", command], capture_output=True, text=True, timeout=EXEC_TIMEOUT
        )
        return proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out after {}s".format(EXEC_TIMEOUT), -1


def main():
    parser = argparse.ArgumentParser(description="Shell Worker")
    parser.add_argument("--gateway", default=DEFAULT_GATEWAY, help="Gateway base URL")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification")
    args = parser.parse_args()

    client = httpx.Client(timeout=10, verify=not args.insecure)
    logger.info("Worker started, gateway=%s", args.gateway)

    while True:
        try:
            poll_path = "/api/command/next"
            resp = client.get(f"{args.gateway}{poll_path}", headers=auth_headers("GET", poll_path))
            data = resp.json()
        except Exception as e:
            logger.error("Failed to poll gateway: %s", e)
            time.sleep(POLL_INTERVAL)
            continue

        if not data:
            time.sleep(POLL_INTERVAL)
            continue

        reqid = data["reqid"]
        command = data["command"]
        user = data.get("user", "root")

        logger.info("Got command: reqid=%s user=%s cmd=%s", reqid, user, command)

        stdout, stderr, exit_code = run_as_user(command, user)
        logger.info("Finished: reqid=%s exit_code=%d", reqid, exit_code)

        try:
            result_path = f"/api/command/{reqid}/result"
            client.post(
                f"{args.gateway}{result_path}",
                json={"stdout": stdout, "stderr": stderr, "exit_code": exit_code},
                headers=auth_headers("POST", result_path),
            )
            logger.info("Result posted: reqid=%s", reqid)
        except Exception as e:
            logger.error("Failed to post result for reqid=%s: %s", reqid, e)


if __name__ == "__main__":
    main()
