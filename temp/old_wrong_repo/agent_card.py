"""
AXIOM A2A Agent Card.

Served at GET /.well-known/agent-card.json per A2A v0.3.0 spec.

Capability flags match actual implementation:
  streaming=false         — message/stream is not in the method allowlist
  pushNotifications=false — no push-notification config endpoints implemented
  stateTransitionHistory=false — tasks/get returns current status only, not history
"""
import os

_ngrok_url = os.environ.get("NGROK_URL", "https://YOUR_NGROK_URL.ngrok.app")

AXIOM_AGENT_CARD = {
    "protocolVersion": "0.3.0",
    "name": "Axiom Customer Intelligence Agent",
    "description": (
        "Three-tier customer service intelligence network. "
        "Resolves billing disputes, technical issues, order status, "
        "and product return requests using intake classification, "
        "parallel external research, and evidence-backed resolutions."
    ),
    "version": "3.0.0",
    "url": f"{_ngrok_url}/a2a/customer_service",
    "preferredTransport": "JSONRPC",
    "capabilities": {
        # message/stream removed from method allowlist — do not advertise
        "streaming": False,
        # No push-notification config endpoints — do not advertise
        "pushNotifications": False,
        # tasks/get returns current state only, not full history
        "stateTransitionHistory": False,
    },
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["application/json", "text/plain"],
    "skills": [
        {
            "id": "customer_service_resolution",
            "name": "Customer Service Resolution",
            "description": (
                "Investigates and resolves supported customer service cases: "
                "billing disputes, technical support, order status, and product returns. "
                "Returns a structured ResolutionPayload with status, summary, "
                "confidence score, and follow-up actions."
            ),
            "tags": ["customer-service", "billing", "orders", "returns", "resolution"],
            "inputModes": ["text/plain"],
            "outputModes": ["application/json", "text/plain"],
        }
    ],
}
