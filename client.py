#!/usr/bin/env python3
"""
Client — 向 Gateway 提交命令并查询结果。
"""

import time
import sys
import argparse

import httpx


def main():
    parser = argparse.ArgumentParser(description="Shell Gateway Client")
    sub = parser.add_subparsers(dest="action")

    run_parser = sub.add_parser("run", help="Submit a command and wait for result")
    run_parser.add_argument("command", nargs="+", help="Command to execute")
    run_parser.add_argument("--user", required=True, help="User to run as")
    run_parser.add_argument("--gateway", default="http://localhost:8000", help="Gateway base URL")
    run_parser.add_argument("--timeout", type=int, default=60, help="Max wait time in seconds")

    submit_parser = sub.add_parser("submit", help="Submit a command, get reqid only")
    submit_parser.add_argument("command", nargs="+", help="Command to execute")
    submit_parser.add_argument("--user", required=True, help="User to run as")
    submit_parser.add_argument("--gateway", default="http://localhost:8000", help="Gateway base URL")

    query_parser = sub.add_parser("query", help="Query result by reqid")
    query_parser.add_argument("reqid", help="Request ID")
    query_parser.add_argument("--gateway", default="http://localhost:8000", help="Gateway base URL")

    args = parser.parse_args()

    if args.action == "run":
        do_run(args)
    elif args.action == "submit":
        do_submit(args)
    elif args.action == "query":
        do_query(args)
    else:
        parser.print_help()


def do_submit(args):
    command = " ".join(args.command)
    resp = httpx.post(f"{args.gateway}/api/command", json={"command": command, "user": args.user})
    resp.raise_for_status()
    data = resp.json()
    print(f"Submitted. reqid={data['reqid']}")


def do_run(args):
    command = " ".join(args.command)
    resp = httpx.post(f"{args.gateway}/api/command", json={"command": command, "user": args.user})
    resp.raise_for_status()
    reqid = resp.json()["reqid"]
    print(f"Submitted. reqid={reqid}")

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        resp = httpx.get(f"{args.gateway}/api/command/{reqid}")
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
    resp = httpx.get(f"{args.gateway}/api/command/{args.reqid}")
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
