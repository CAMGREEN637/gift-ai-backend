#vector_store.py
from pathlib import Path
import chromadb

# -------------------------------------------------
# Resolve base directory
# -------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
CHROMA_DIR = BASE_DIR / "chroma_db"

# -------------------------------------------------
# Force-create directory
# -------------------------------------------------
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

print("🧠 Chroma persist directory:", CHROMA_DIR)

# -------------------------------------------------
# ✅ PERSISTENT CLIENT (THIS IS THE FIX)
# -------------------------------------------------
client = chromadb.PersistentClient(path=str(CHROMA_DIR))

# -------------------------------------------------
# SINGLE collection
# -------------------------------------------------
collection = client.get_or_create_collection(name="gifts")


