#!/usr/bin/env python3
"""Pure-Python Merkle tree utilities for AuditorClaw.

Supports 2-4 leaves (step hashes from Scanner/Compliance/Optimizer).
Uses SHA256 for all hashing. No external dependencies.
"""

import hashlib


def sha256(data: str) -> str:
    """SHA256 hex digest of a string."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _hash_pair(left: str, right: str) -> str:
    """Hash two hex strings together (sorted to ensure determinism)."""
    combined = min(left, right) + max(left, right)
    return sha256(combined)


def build_merkle_tree(leaves: list[str]) -> dict:
    """Build a Merkle tree from a list of hex-string leaves.

    Args:
        leaves: List of SHA256 hex strings (2-4 items).

    Returns:
        {root, leaves, layers} where layers[0]=leaves, layers[-1]=[root].
    """
    if len(leaves) < 2:
        raise ValueError("Need at least 2 leaves to build a Merkle tree.")

    layers = [list(leaves)]

    current = list(leaves)
    while len(current) > 1:
        next_layer = []
        for i in range(0, len(current), 2):
            if i + 1 < len(current):
                next_layer.append(_hash_pair(current[i], current[i + 1]))
            else:
                # Odd leaf: duplicate it
                next_layer.append(_hash_pair(current[i], current[i]))
        layers.append(next_layer)
        current = next_layer

    return {
        "root": current[0],
        "leaves": list(leaves),
        "layers": layers,
    }


def get_proof(tree: dict, leaf_index: int) -> list[dict]:
    """Get Merkle proof for a leaf at given index.

    Returns list of {hash, position} pairs needed to reconstruct root.
    """
    layers = tree["layers"]
    proof = []
    idx = leaf_index

    for layer in layers[:-1]:  # Skip root layer
        if idx % 2 == 0:
            sibling_idx = idx + 1
            position = "right"
        else:
            sibling_idx = idx - 1
            position = "left"

        if sibling_idx < len(layer):
            proof.append({"hash": layer[sibling_idx], "position": position})
        else:
            proof.append({"hash": layer[idx], "position": position})

        idx = idx // 2

    return proof


def verify_proof(proof: list[dict], leaf: str, root: str) -> bool:
    """Verify a Merkle proof against a known root.

    Args:
        proof: List of {hash, position} pairs from get_proof().
        leaf: The leaf hash being verified.
        root: The expected Merkle root.

    Returns:
        True if the proof is valid.
    """
    current = leaf
    for step in proof:
        if step["position"] == "left":
            current = _hash_pair(step["hash"], current)
        else:
            current = _hash_pair(current, step["hash"])
    return current == root
