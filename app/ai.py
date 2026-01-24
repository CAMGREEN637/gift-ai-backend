from openai import OpenAI
import os
from dotenv import load_dotenv
from openai.types.chat import (
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam
)

load_dotenv(r"C:\Users\camry\PycharmProjects\PythonProject\gift-ai-backend\.env")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def run_gift_recommender(prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            ChatCompletionSystemMessageParam(role="system", content="You output only valid JSON"),
            ChatCompletionUserMessageParam(role="user", content=prompt)
        ]
    )
    return response.choices[0].message.content

