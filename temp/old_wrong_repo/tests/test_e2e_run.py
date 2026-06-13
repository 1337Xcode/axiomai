"""
End-to-end smoke test script (manual / pre-event checklist).

Run against a live stack:
  .axiom_env\\Scripts\\python.exe tests/test_e2e_run.py

Requires gateway on localhost:8080 and AXIOM_MODE=development or grading.
"""
import json
import sys

import httpx
import pytest


@pytest.mark.skip(reason="Requires live gateway + LLM; run manually via __main__")
def test_e2e_live_gateway():
    """Collected placeholder — use run_e2e_smoke() for manual runs."""
    run_e2e_smoke()


def run_e2e_smoke() -> bool:
    """Send a billing dispute through the gateway; return True on success."""
    url = "http://localhost:8080/a2a/customer_service"

    payload = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": "test_e2e_123",
        "params": {
            "message": {
                "role": "user",
                "messageId": "msg_e2e_123",
                "parts": [
                    {
                        "kind": "text",
                        "text": (
                            "I need help with a billing dispute. "
                            "My account number is ACC-12345."
                        ),
                    }
                ],
            },
        },
    }

    print("Sending E2E request to Gateway...")
    try:
        resp = httpx.post(url, json=payload, timeout=120.0)
        print(f"Response Status Code: {resp.status_code}")
        data = resp.json()
        print(json.dumps(data, indent=2))

        assert data.get("jsonrpc") == "2.0"
        assert data.get("id") == "test_e2e_123"
        assert "result" in data
        assert data["result"]["status"]["state"] == "completed"
        print("\nSUCCESS: E2E pipeline verified.")
        return True
    except Exception as e:
        print(f"\nFAILURE: E2E pipeline failed: {e}")
        return False


if __name__ == "__main__":
    ok = run_e2e_smoke()
    sys.exit(0 if ok else 1)
