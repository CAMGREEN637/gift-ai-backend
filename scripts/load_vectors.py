import json
from pathlib import Path

from app.vector_store import collection


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
# Resolve project root and data file
# --------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "gifts_embedded.json"

if not DATA_PATH.exists():
    raise FileNotFoundError(f"Data file not found: {DATA_PATH}")


# --------------------------------------------------
# Load embedded gift data
# --------------------------------------------------
with open(DATA_PATH, "r", encoding="utf-8") as f:
    items = json.load(f)

print("LOAD SCRIPT COUNT (before):", collection.count())


# --------------------------------------------------
# Insert items into Chroma
# --------------------------------------------------
count = 0

for item in items:
    collection.add(
        ids=[item["id"]],
        embeddings=[item["embedding"]],
        metadatas=[sanitize_metadata(item["metadata"])],
    )
    count += 1


print(f"Loaded {count} gifts into vector store")
print("LOAD SCRIPT COUNT (after):", collection.count())
input("Press Enter to exit...")
