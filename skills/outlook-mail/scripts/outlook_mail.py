#!/usr/bin/env python3
"""Draft-only Outlook CLI. Credentials and mailbox state stay outside the skill."""
import argparse
import json
from pathlib import Path
from outlooklib.auth import connect_token, load_connection, login
from outlooklib.client import MailError
from outlooklib.storage import state_dir


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("connect", help="Use an existing authorised private token file")
    c.add_argument("--token-file", required=True)
    c.add_argument("--account", required=True)
    c.add_argument("--backend", choices=("graph", "outlook-rest"), default="outlook-rest")
    c.add_argument("--experimental", action="store_true")
    c = sub.add_parser("login", help="Sign into an approved Graph public-client app")
    c.add_argument("--client-id", required=True)
    c.add_argument("--tenant", default="organizations")
    c.add_argument("--account", required=True)
    sub.add_parser("doctor")
    sub.add_parser("disconnect")
    for name in ("list", "search"):
        c = sub.add_parser(name)
        c.add_argument("--folder", default="inbox")
        c.add_argument("--limit", type=int, default=50)
        if name == "search":
            c.add_argument("query")
    c = sub.add_parser("read")
    c.add_argument("message_id")
    c = sub.add_parser("attachments")
    a = c.add_subparsers(dest="attachment_action", required=True)
    c = a.add_parser("list")
    c.add_argument("message_id")
    c = a.add_parser("download")
    c.add_argument("message_id")
    c.add_argument("attachment_id")
    c.add_argument("--output", required=True)
    for name in ("draft", "reply-draft"):
        c = sub.add_parser(name)
        c.add_argument("--body-file", required=True)
        c.add_argument("--request-id", required=True, help="Reuse this ID after interruptions; never blindly retry with a new ID")
        if name == "draft":
            c.add_argument("--to", action="append", required=True)
            c.add_argument("--cc", action="append", default=[])
            c.add_argument("--subject", required=True)
        else:
            c.add_argument("message_id")
            c.add_argument("--reply-all", action="store_true")
    c = sub.add_parser("pump", help="Primary OWA session bridge setup, status and helper lifecycle")
    a = c.add_subparsers(dest="pump_action", required=True)
    c = a.add_parser("setup")
    c.add_argument("--account", required=True)
    c.add_argument("--port", type=int, default=8769)
    c.add_argument("--start", action="store_true", help="Install/start an owned Linux systemd user service")
    c.add_argument("--open", action="store_true", help="Open the local userscript installer after starting")
    for action in ("serve", "status", "stop"):
        a.add_parser(action)
    c = sub.add_parser("organise")
    o = c.add_subparsers(dest="organise_action", required=True)
    c = o.add_parser("plan")
    c.add_argument("--folder", default="inbox")
    c.add_argument("--limit", type=int, default=50)
    c.add_argument("--output")
    c = o.add_parser("assign")
    c.add_argument("plan")
    c.add_argument("--topic", required=True)
    c.add_argument("--message-id", action="append", required=True)
    c = o.add_parser("apply")
    c.add_argument("plan")
    c = o.add_parser("undo")
    c.add_argument("journal")
    return p


def run(args, transport=None):
    if args.command == "connect":
        return connect_token(args.token_file, args.account, args.backend, args.experimental, transport)
    if args.command == "login":
        return login(args.client_id, args.tenant, args.account, transport)
    if args.command == "disconnect":
        if (state_dir() / "pump.json").exists():
            from outlooklib.pump import stop
            stop()
        for name in ("config.json", "oauth-cache.json"):
            (state_dir() / name).unlink(missing_ok=True)
        return {"disconnected": True, "source_token_file_deleted": False}
    if args.command == "pump":
        from outlooklib.pump import prepare, serve, status, stop
        if args.pump_action == "setup":
            return prepare(args.account, args.port, args.start, args.open)
        if args.pump_action == "status":
            return status()
        if args.pump_action == "stop":
            return stop()
        serve()
        return {"stopped": True}
    client, config = load_connection(transport)
    if args.command == "doctor":
        return {"connected": True, "account": config["account"], "backend": config["backend"],
                "experimental": config["backend"] == "outlook-rest", "mode": config["mode"]}
    if args.command in ("list", "search"):
        messages = client.list_messages(args.folder, args.limit, getattr(args, "query", None))
        return {"messages": messages, "count": len(messages), "folder": args.folder}
    if args.command == "read":
        return {"message": client.message(args.message_id)}
    if args.command == "attachments":
        from outlooklib.attachments import attachments, download
        if args.attachment_action == "list":
            return {"attachments": attachments(client, args.message_id)}
        return download(client, args.message_id, args.attachment_id, args.output)
    if args.command in ("draft", "reply-draft"):
        from outlooklib.drafts import create
        body_path = Path(args.body_file)
        if body_path.stat().st_size > 1024 * 1024:
            raise ValueError("Body file exceeds 1 MiB")
        text = body_path.read_text(encoding="utf-8")
        return create(client, config["account"], args.request_id, text,
                      to=getattr(args, "to", None), cc=getattr(args, "cc", None),
                      subject=getattr(args, "subject", None), source=getattr(args, "message_id", None),
                      reply_all=getattr(args, "reply_all", False))
    if args.command == "organise":
        from outlooklib.organise import make_plan, assign, apply, undo
        if args.organise_action == "plan":
            return make_plan(client, config, args.folder, args.limit, args.output)
        if args.organise_action == "assign":
            return assign(args.plan, config, args.topic, args.message_id)
        if args.organise_action == "apply":
            return apply(client, config, args.plan)
        return undo(client, config, args.journal)
    raise ValueError("Unknown command")


def main(argv=None, transport=None):
    args = parser().parse_args(argv)
    try:
        result = run(args, transport)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except MailError as exc:
        print(json.dumps({"error": exc.code, "message": str(exc), "status": exc.status}))
        return 2
    except (ValueError, KeyError, TypeError, OSError):
        print(json.dumps({"error": "invalid_input_or_state",
                          "message": "Invalid input or inaccessible state. Check command arguments, private file permissions and configuration."}))
        return 2
    except Exception:
        # External auth libraries can raise exceptions with response details. Keep
        # that material out of agent context; reproduce with synthetic tests instead.
        print(json.dumps({"error": "unexpected_failure", "message": "Operation failed without exposing response/credential details. Inspect private operation receipts/journals before retrying a write."}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
