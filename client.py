#!/usr/bin/env python3
"""
Client — 向 Gateway 提交命令并查询结果。
"""

import hashlib
import hmac
import os
import time
import sys
import argparse

import httpx

SHARED_SECRET = os.environ.get("SHARED_SECRET", "")
VERIFY_SSL = True


def auth_headers(method: str, path: str) -> dict:
    if not SHARED_SECRET:
        return {}
    ts = str(int(time.time()))
    payload = f"{ts}\n{method}\n{path}".encode()
    sig = hmac.new(SHARED_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return {"Authorization": f"HMAC-SHA256 {sig}", "X-Timestamp": ts}


def mk_client() -> httpx.Client:
    return httpx.Client(verify=VERIFY_SSL)


def get_command(args) -> str:
    if args.command:
        return " ".join(args.command)
    if not sys.stdin.isatty():
        return sys.stdin.read().rstrip("\n")
    print("Enter command (Ctrl+D to finish):", file=sys.stderr)
    return sys.stdin.read().rstrip("\n")


def main():
    parser = argparse.ArgumentParser(description="Shell Gateway Client")
    sub = parser.add_subparsers(dest="action")

    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification")

    run_parser = sub.add_parser("run", parents=[parent], help="Submit a command and wait for result")
    run_parser.add_argument("command", nargs="*", help="Command to execute (reads from stdin if omitted)")
    run_parser.add_argument("--user", required=True, help="User to run as")
    run_parser.add_argument("--gateway", default="http://localhost:8000", help="Gateway base URL")
    run_parser.add_argument("--timeout", type=int, default=60, help="Max wait time in seconds")

    submit_parser = sub.add_parser("submit", parents=[parent], help="Submit a command, get reqid only")
    submit_parser.add_argument("command", nargs="*", help="Command to execute (reads from stdin if omitted)")
    submit_parser.add_argument("--user", required=True, help="User to run as")
    submit_parser.add_argument("--gateway", default="http://localhost:8000", help="Gateway base URL")

    query_parser = sub.add_parser("query", parents=[parent], help="Query result by reqid")
    query_parser.add_argument("reqid", help="Request ID")
    query_parser.add_argument("--gateway", default="http://localhost:8000", help="Gateway base URL")

    args = parser.parse_args()
    global VERIFY_SSL
    if args.insecure:
        VERIFY_SSL = False

    if args.action == "run":
        do_run(args)
    elif args.action == "submit":
        do_submit(args)
    elif args.action == "query":
        do_query(args)
    else:
        parser.print_help()


def do_submit(args):
    command = get_command(args)
    path = "/api/command"
    resp = mk_client().post(f"{args.gateway}{path}", json={"command": command, "user": args.user},
                            headers=auth_headers("POST", path))
    resp.raise_for_status()
    data = resp.json()
    print(f"Submitted. reqid={data['reqid']}")


def do_run(args):
    command = get_command(args)
    path = "/api/command"
    resp = mk_client().post(f"{args.gateway}{path}", json={"command": command, "user": args.user},
                            headers=auth_headers("POST", path))
    resp.raise_for_status()
    reqid = resp.json()["reqid"]
    print(f"Submitted. reqid={reqid}")

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        qpath = f"/api/command/{reqid}"
        resp = mk_client().get(f"{args.gateway}{qpath}", headers=auth_headers("GET", qpath))
        resp.raise_for_status()
        data = resp.json()
        if data["status"] == "done":
            print(f"Status: done, exit_code={data['exit_code']}")
            if data["stdout"]:
                print("--- stdout ---")
                print(data["stdout"], end="")
            if data["stderr"]:
                print("--- stderr ---")
                print(data["stderr"], end="")
            sys.exit(data["exit_code"] or 0)
        print(f"Status: {data['status']} (polling...)")
        time.sleep(1)

    print("Timeout waiting for result")
    sys.exit(1)


def do_query(args):
    qpath = f"/api/command/{args.reqid}"
    resp = mk_client().get(f"{args.gateway}{qpath}", headers=auth_headers("GET", qpath))
    if resp.status_code == 404:
        print(f"reqid {args.reqid} not found")
        return
    resp.raise_for_status()
    data = resp.json()
    print(f"reqid:     {data['reqid']}")
    print(f"status:    {data['status']}")
    print(f"user:      {data['user']}")
    print(f"command:   {data['command']}")
    print(f"exit_code: {data['exit_code']}")
    if data["stdout"]:
        print("--- stdout ---")
        print(data["stdout"], end="")
    if data["stderr"]:
        print("--- stderr ---")
        print(data["stderr"], end="")


if __name__ == "__main__":
    main()
