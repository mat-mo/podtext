import os
import json
import time
import requests
import feedparser
from slugify import slugify
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

# Target Episode Slug
TARGET_SLUG = "htshvbh-rtyq-qrtyb"
CONFIG_PATH = "podtext/config.yaml"
TEMP_FILE = "podtext/tmp/debug_audio.mp3"
RAW_OUTPUT = "podtext/tmp/debug_raw_response.txt"

api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

def get_audio_url():
    import yaml
    with open(CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
    
    url = config['feeds'][0]['url']
    print(f"Scanning feed: {url}")
    d = feedparser.parse(url)
    
    for entry in d.entries:
        if slugify(entry.title) == TARGET_SLUG:
            print(f"Found episode: {entry.title}")
            for link in entry.links:
                if link.type == 'audio/mpeg':
                    return link.href
    return None

def main():
    # 1. Download
    url = get_audio_url()
    if not url:
        print(f"Could not find episode with slug: {TARGET_SLUG}")
        return

    print(f"Downloading {url}...")
    with requests.get(url, stream=True) as r:
        with open(TEMP_FILE, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

    # 2. Upload
    print("Uploading to Gemini...")
    file = client.files.upload(file=TEMP_FILE)
    print(f"Uploaded: {file.name}")
    
    while file.state == "PROCESSING":
        time.sleep(2)
        file = client.files.get(name=file.name)
    
    if file.state != "ACTIVE":
        print(f"File failed state: {file.state}")
        return

    # 3. Generate with diagnostics
    print("Sending request to Gemini...")
    prompt = """
    Transcribe this podcast episode accurately. Identify speakers. 
    Format as JSON: {"segments": [{"speaker": "...", "text": "..."}]}
    """
    
    try:
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=[file, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )
        
        # 4. Diagnose
        print("\n--- DIAGNOSTICS ---")
        
        # Check Candidates
        if not response.candidates:
            print("CRITICAL: No candidates returned (Blocked completely).")
        else:
            cand = response.candidates[0]
            print(f"Finish Reason: {cand.finish_reason}")
            
            # Safety Ratings
            if cand.safety_ratings:
                print("\nSafety Ratings:")
                for rate in cand.safety_ratings:
                    print(f"  - {rate.category}: {rate.probability}")
            
            # Token Usage (if available in usage_metadata)
            if response.usage_metadata:
                print(f"\nToken Usage: Input: {response.usage_metadata.prompt_token_count}, Output: {response.usage_metadata.candidates_token_count}")

        # Save Raw Response
        print(f"\nSaving raw response to {RAW_OUTPUT}...")
        with open(RAW_OUTPUT, "w") as f:
            f.write(response.text if response.text else "(Empty Response)")
            
    except Exception as e:
        print(f"API Request Failed: {e}")
    
    finally:
        client.files.delete(name=file.name)

if __name__ == "__main__":
    main()
