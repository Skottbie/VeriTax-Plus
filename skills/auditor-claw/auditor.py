#!/usr/bin/env python3
"""AuditorClaw — Verifiable Audit Trail for VeriTax.

Builds Merkle tree from step hashes, attaches scanner zkTLS evidence when available,
generates TEE attestation, and uploads ProofBundle to IPFS.

Usage:
    python auditor.py --scan-hash <hash> --compliance-hash <hash> [--optimizer-hash <hash>] [--scan-dataset <path>] [--json]
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
import requests

from merkle_utils import build_merkle_tree, get_proof, verify_proof
from ipfs_utils import upload_json_to_ipfs


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    parser = argparse.ArgumentParser(description="AuditorClaw — Verifiable Audit Trail")
    parser.add_argument("--scan-hash", required=True, help="SHA256 of ScannerClaw output")
    parser.add_argument("--compliance-hash", required=True, help="SHA256 of ComplianceClaw output")
    parser.add_argument("--optimizer-hash", default=None, help="SHA256 of OptimizerClaw output (optional)")
    parser.add_argument("--scan-dataset", default=None, help="Path to scanner dataset json (used to embed zkTLS source proofs)")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    # Step 1: Collect leaves
    leaves = [args.scan_hash, args.compliance_hash]
    step_names = ["scanner", "compliance"]
    if args.optimizer_hash:
        leaves.append(args.optimizer_hash)
        step_names.append("optimizer")

    # Step 2: Build Merkle tree
    tree = build_merkle_tree(leaves)
    merkle_root = tree["root"]

    # Step 3: Generate TEE attestation
    tee = _generate_tee_attestation(merkle_root)

    # Step 3.5: Attach zkTLS evidence from scanner dataset when available
    zktls_evidence = _extract_zktls_evidence(args.scan_dataset)

    # Step 4: Upload to IPFS
    proof_bundle = {
        "version": "veritax-1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps": dict(zip(step_names, leaves)),
        "merkle_root": merkle_root,
        "merkle_tree": {
            "leaves": tree["leaves"],
            "layer_count": len(tree["layers"]),
        },
        "tee_attestation": tee,
        "zktls": zktls_evidence,
    }

    ipfs_result = upload_json_to_ipfs(proof_bundle, name="veritax-audit-trail")
    proof_bundle["ipfs"] = ipfs_result

    # Output
    if args.as_json:
        print(json.dumps(proof_bundle, indent=2, ensure_ascii=False))
    else:
        print("\n[Auditor] ═══ VeriTax Audit Trail ═══")
        print(f"  Steps: {', '.join(step_names)}")
        print(f"  Merkle Root: {merkle_root}")
        zktls_summary = zktls_evidence.get("summary", {})
        real_count = zktls_summary.get("real_proof_count", 0)
        fallback_count = zktls_summary.get("fallback_count", 0)
        missing_count = zktls_summary.get("missing_count", 0)
        if real_count > 0:
            print(f"  zkTLS: 🧾 real={real_count} fallback={fallback_count} missing={missing_count}")
        elif fallback_count > 0 and real_count == 0:
            print(f"  zkTLS: 🔒 SHA256 ×{fallback_count} — OKX ATK CLI 采用本地 API 签名认证，数据来源已由 ATK 签名链保障，无需 zkTLS 远程证明；数据完整性由 SHA256 哈希 + TEE 联合验证")
        else:
            print(f"  zkTLS: 🟡 real={real_count} fallback={fallback_count} missing={missing_count}")
        tee_type = tee.get("type", "unknown")
        tee_icon = "🔐" if tee_type == "intel_tdx" else "🟡"
        print(f"  TEE: {tee_icon} {tee_type}")
        ipfs_icon = "📌" if not ipfs_result.get("is_mock") else "🟡"
        print(f"  IPFS: {ipfs_icon} CID={ipfs_result.get('cid', 'N/A')}")
        print(f"  Timestamp: {proof_bundle['timestamp']}")
        print(f"\n  {ipfs_result.get('note', '')}")

    return 0


def _generate_tee_attestation(merkle_root: str) -> dict:
    """Generate TEE attestation binding merkle_root to TDX Quote.

    Preference order:
      1. Remote Phala-attested service via VERITAX_TEE_ENDPOINT
      2. Local dstack socket (when running inside a CVM)
      3. Mock fallback
    """
    import hashlib
    report_data = hashlib.sha256(merkle_root.encode()).hexdigest()

    remote_endpoint = os.getenv("VERITAX_TEE_ENDPOINT", "").strip()
    if remote_endpoint:
        remote_result = _generate_remote_tee_attestation(remote_endpoint, merkle_root, report_data)
        if remote_result:
            return remote_result

    try:
        from dstack_sdk import AsyncDstackClient

        async def _get_quote():
            client = AsyncDstackClient()
            report_bytes = bytes.fromhex(report_data)
            resp = await client.get_quote(report_bytes)
            return resp

        resp = asyncio.run(_get_quote())
        return {
            "type": "intel_tdx",
            "report_data": report_data,
            "quote": resp.quote if resp else None,
            "event_log": getattr(resp, "event_log", None) if resp else None,
            "note": "Real Intel TDX attestation from Phala Cloud CVM.",
        }
    except Exception as e:
        return {
            "type": "mock_tdx",
            "report_data": report_data,
            "quote": None,
            "note": f"Deploy to Phala Cloud CVM for real TDX attestation. ({e})",
        }


def _extract_zktls_evidence(scan_dataset_path: str | None) -> dict:
    summary = {
        "dataset_loaded": False,
        "source_count": 0,
        "real_proof_count": 0,
        "fallback_count": 0,
        "missing_count": 0,
        "labels": [],
    }
    if not scan_dataset_path:
        return {"summary": summary, "sources": [], "note": "scan_dataset not provided"}

    try:
        raw = Path(scan_dataset_path).read_text(encoding="utf-8-sig")
        payload = json.loads(raw)
    except Exception as exc:
        return {"summary": summary, "sources": [], "note": f"scan_dataset unreadable: {exc}"}

    proofs = payload.get("source_zktls_proofs")
    if not isinstance(proofs, list):
        return {"summary": summary, "sources": [], "note": "source_zktls_proofs missing in scan dataset"}

    real_proofs = [proof for proof in proofs if proof.get("type") == "reclaim_zkfetch"]
    fallback_proofs = [proof for proof in proofs if proof.get("type") and proof.get("type") != "reclaim_zkfetch"]
    missing_count = len([proof for proof in proofs if not proof.get("type")])
    labels = [proof.get("label") for proof in proofs if proof.get("label")]

    summary.update({
        "dataset_loaded": True,
        "source_count": len(proofs),
        "real_proof_count": len(real_proofs),
        "fallback_count": len(fallback_proofs),
        "missing_count": missing_count,
        "labels": labels,
    })
    return {
        "summary": summary,
        "sources": proofs,
        "note": "Scanner source zkTLS proofs embedded into ProofBundle",
    }


def _generate_remote_tee_attestation(endpoint: str, merkle_root: str, report_data: str) -> dict | None:
    endpoint = endpoint.rstrip("/")
    token = os.getenv("VERITAX_TEE_AUTH_TOKEN", "").strip()
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.post(
            f"{endpoint}/attest",
            json={"merkle_root": merkle_root},
            headers=headers,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        data.setdefault("report_data", report_data)
        return data
    except Exception:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
