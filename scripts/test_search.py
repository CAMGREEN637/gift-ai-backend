from openai import OpenAI
from dotenv import load_dotenv
import os

from app.vector_store import collection


# ------------------------------------------------------------------
# Load environment variables
# ------------------------------------------------------------------
load_dotenv()  # automatically finds .env at project root


# ------------------------------------------------------------------
# Initialize OpenAI client
# ------------------------------------------------------------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ------------------------------------------------------------------
# Create query embedding
# ------------------------------------------------------------------
query = "romantic gift under $150"

query_embedding = client.embeddings.create(
    model="text-embedding-3-small",
    input=query
).data[0].embedding


# ------------------------------------------------------------------
# Query vector store
# ------------------------------------------------------------------
results = collection.query(
    query_embeddings=[query_embedding],
    n_results=5
)


# ------------------------------------------------------------------
# Display results
# ------------------------------------------------------------------
print("Results:")
for meta in results["metadatas"][0]:
    print(meta["name"], "-", meta.get("price"))

print("Vector count:", collection.count())