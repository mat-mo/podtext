import os
from google import genai
from dotenv import load_dotenv

load_dotenv("podtext/.env")
api_key = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=api_key)

print("Listing available models...")
# The new SDK models.list returns a list of model objects
# Each object has a 'name' attribute
for model in client.models.list(config={'page_size': 50}):
    print(f"- {model.name}")