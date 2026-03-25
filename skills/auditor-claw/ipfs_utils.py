#!/usr/bin/env python3
"""Pinata IPFS upload utilities for AuditorClaw.

Uses Pinata REST API to pin JSON data to IPFS.
Falls back to mock CID when PINATA_JWT is not configured.
"""

import json
import os
from urllib import request, error


PINATA_PIN_URL = "https://api.pinata.cloud/pinning/pinJSONToIPFS"


def upload_json_to_ipfs(data: dict, name: str = "veritax-audit") -> dict:
    """Upload JSON data to IPFS via Pinata.

    Args:
        data: Dict to pin as JSON.
        name: Human-readable name for the pin.

    Returns:
        {cid, is_mock, note}
    """
    jwt = os.environ.get("PINATA_JWT", "")
    if not jwt:
        # Mock fallback — no Pinata JWT configured
        import hashlib
        mock_cid = "Qm" + hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()[:44]
        return {
            "cid": mock_cid,
            "is_mock": True,
            "note": "Mock CID — set PINATA_JWT in .env for real IPFS upload.",
        }

    payload = json.dumps({
        "pinataContent": data,
        "pinataMetadata": {"name": name},
    }).encode("utf-8")

    req = request.Request(
        PINATA_PIN_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {jwt}",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            return {
                "cid": result.get("IpfsHash", ""),
                "is_mock": False,
                "note": "Pinned to IPFS via Pinata.",
            }
    except error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {
            "cid": "",
            "is_mock": True,
            "note": f"Pinata upload failed: HTTP {e.code} — {body[:200]}",
        }
    except Exception as e:
        return {
            "cid": "",
            "is_mock": True,
            "note": f"Pinata upload failed: {e}",
        }
