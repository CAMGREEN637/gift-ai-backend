import json
import argparse
from pathlib import Path

from app.vector_store import collection

# --------------------------------------------------
# CLI Arguments
# --------------------------------------------------
parser = argparse.ArgumentParser(description="Load gift vectors into Chroma")
parser.add_argument(
    "--reset",
    action="store_true",
    help="Delete all existing vectors before loading",
)
args = parser.parse_args()

# --------------------------------------------------
# Metadata sanitizer (REQUIRED for Chroma)
# --------------------------------------------------
def sanitize_metadata(metadata: dict) -> dict:
    clean = {}
    for key, value in metadata.items():
        if isinstance(value, list):
            clean[key] = ", ".join(map(str, value))
        elif isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value
        else:
            clean[key] = str(value)
    return clean

# --------------------------------------------------
# Resolve data path
# --------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "gifts_embedded.json"

if not DATA_PATH.exists():
    raise FileNotFoundError(f"Data file not found: {DATA_PATH}")

# --------------------------------------------------
# Load embedded gifts
# --------------------------------------------------
with open(DATA_PATH, "r", encoding="utf-8") as f:
    items = json.load(f)

incoming_ids = [item["id"] for item in items]

print("📦 Incoming gifts:", len(incoming_ids))
print("🧠 Existing vectors:", collection.count())

# --------------------------------------------------
# RESET MODE
# --------------------------------------------------
if args.reset:
    print("⚠️  --reset flag detected")
    print("🗑️  Deleting entire collection...")
    collection.delete(where={})
    print("✅ Collection cleared")

# --------------------------------------------------
# SAFETY CHECK (non-reset mode)
# --------------------------------------------------
elif collection.count() > 0:
    existing = collection.get(ids=incoming_ids)
    existing_ids = set(existing["ids"]) if existing["ids"] else set()

    if existing_ids:
        print("⚠️  WARNING: Some gift IDs already exist in Chroma:")
        for gid in sorted(existing_ids):
            print(f"   - {gid}")

        print("♻️  These gifts will be UPDATED (delete + reinsert)")

        # Delete only conflicting IDs
        collection.delete(ids=list(existing_ids))

# --------------------------------------------------
# INSERT UPDATED VECTORS
# --------------------------------------------------
added = 0

for item in items:
    collection.add(
        ids=[item["id"]],
        embeddings=[item["embedding"]],
        metadatas=[sanitize_metadata(item["metadata"])],
    )
    added += 1

# --------------------------------------------------
# Final status
# --------------------------------------------------
print("✅ Load complete")
print("➕ Gifts loaded:", added)
print("🧠 Total vectors now:", collection.count())


