import json
import os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# Load env vars
load_dotenv(r"C:\Users\camry\PycharmProjects\PythonProject\gift-ai-backend\.env")

if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("OPENAI_API_KEY not found")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def build_embedding_text(gift):
    return f"""
{gift['name']}. {gift['description']}
Categories: {", ".join(gift['categories'])}.
Interests: {", ".join(gift['interests'])}.
Occasions: {", ".join(gift['occasions'])}.
Vibe: {", ".join(gift['vibe'])}.
Personality traits: {", ".join(gift['personality_traits'])}.
"""


with open(DATA_DIR / "gifts.json", "r", encoding="utf-8") as f:
    gifts = json.load(f)

embedded = []

for gift in gifts:
    text = build_embedding_text(gift)
    embedding = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    ).data[0].embedding

    embedded.append({
        "id": gift["id"],
        "embedding": embedding,
        "metadata": gift
    })

with open(DATA_DIR / "gifts_embedded.json", "w", encoding="utf-8") as f:
    json.dump(embedded, f, indent=2)

print(f"Embedded {len(embedded)} gifts")
