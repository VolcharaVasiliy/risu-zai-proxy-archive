import io
import json
import os
import sys
from contextlib import redirect_stdout


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from py.observability import header_summary, log_event, redact, request_context, request_id


def test_redact_nested_credentials():
    secret = "Bearer super-secret-token-value"
    payload = redact({"headers": {"Authorization": secret}, "message": secret})
    assert "super-secret-token-value" not in json.dumps(payload)
    assert "redacted" in payload["headers"]["Authorization"]


def test_header_summary_keeps_names_only():
    summary = header_summary(
        {
            "Authorization": "Bearer hidden",
            "Cookie": "session=hidden",
            "Content-Type": "application/json",
        }
    )
    assert "authorization" in summary["names"]
    assert summary["sensitive_present"] == {"authorization": True, "cookie": True}
    assert "hidden" not in json.dumps(summary)


def test_request_context_and_structured_event():
    output = io.StringIO()
    previous = os.environ.get("PROXY_LOG_LEVEL")
    os.environ["PROXY_LOG_LEVEL"] = "debug"
    try:
        with request_context("client-request-7"):
            assert request_id() == "client-request-7"
            with redirect_stdout(output):
                log_event("test_event", value="ok")
    finally:
        if previous is None:
            os.environ.pop("PROXY_LOG_LEVEL", None)
        else:
            os.environ["PROXY_LOG_LEVEL"] = previous
    event = json.loads(output.getvalue())
    assert event["request_id"] == "client-request-7"
    assert event["event"] == "test_event"


def main():
    test_redact_nested_credentials()
    test_header_summary_keeps_names_only()
    test_request_context_and_structured_event()
    print("observability tests: ok")


if __name__ == "__main__":
    main()
