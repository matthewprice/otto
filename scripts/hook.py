#!/usr/bin/env python3
"""Hook dispatcher. Observers only: always exits 0 and never prints to the model.

  hook.py stop          Stop: record the finished session as a ledger row (numbers only)
  hook.py stopfailure   StopFailure: record a short failure label for the session
  hook.py notification  Notification: count it (an unattended run waiting on a human is a finding)
  hook.py sessionstart  SessionStart: on resume, warn if resuming a cold cache is expensive

Reads the hook JSON from stdin. If OTTO_AUTOMATION is set (the wrapper sets it), the row is
tagged with that automation name. Anything unexpected is logged to state/errors.log and ignored.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LABELS = {"rate_limit": "rate_limit", "authentication_failed": "auth", "billing_error": "budget",
          "invalid_request": "error", "server_error": "error", "max_output_tokens": "error", "unknown": "error"}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        import ledger
        import otto_common as oc
        from pathlib import Path
        data = json.loads(sys.stdin.read() or "{}")
        sid = str(data.get("session_id") or "")
        auto = os.environ.get("OTTO_AUTOMATION") or None
        if mode == "stop":
            tp = data.get("transcript_path")
            if tp and os.path.isfile(tp):
                row = ledger.row_from_transcript(Path(tp), auto, "local-cli" if auto else "interactive")
                if row:
                    ledger.upsert_run(oc.otto_home(), row)
        elif mode == "stopfailure":
            label = LABELS.get(str(data.get("error") or data.get("error_type") or "unknown"), "error")
            ledger.add_event(oc.otto_home(), "stop_failure", label, sid, auto or "")
        elif mode == "notification":
            ledger.add_event(oc.otto_home(), "notification", "waiting", sid, auto or "")
        elif mode == "sessionstart":
            cfg = oc.load_config()
            usd = data.get("estimated_cache_write_usd")
            if data.get("source") == "resume" and isinstance(usd, (int, float)) and usd >= float(cfg.get("resume_cost_warn_usd") or 0.5):
                print(json.dumps({"systemMessage": "Otto: resuming this session re-writes its cache, about $%.2f. "
                                  "A fresh session with a short summary is cheaper." % usd}))
    except Exception as e:
        try:
            import otto_common as oc
            oc.log_error("hook %s: %s" % (mode, e.__class__.__name__))
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
