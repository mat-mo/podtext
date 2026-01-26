import os
import json
import time
import requests
import yaml
import feedparser
import subprocess
from email.utils import formatdate
from slugify import slugify
from jinja2 import Environment, FileSystemLoader
from dotenv import load_dotenv
from tqdm import tqdm
from google import genai
from google.genai import types

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.yaml')
DB_PATH = os.path.join(BASE_DIR, 'db.json')
OUTPUT_DIR = os.path.join(BASE_DIR, 'docs')
EPISODES_DIR = os.path.join(OUTPUT_DIR, 'episodes')
TEMP_DIR = os.path.join(BASE_DIR, 'tmp')

# Ensure directories
for d in [OUTPUT_DIR, EPISODES_DIR, TEMP_DIR]:
    os.makedirs(d, exist_ok=True)

# Configure Gemini
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("WARNING: GEMINI_API_KEY not found in .env file. Please add it.")
    client = None
else:
    client = genai.Client(api_key=api_key)

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

def load_db():
    if os.path.exists(DB_PATH):
        with open(DB_PATH, 'r') as f:
            return json.load(f)
    return {"processed": [], "episodes": []}

def save_db(db):
    with open(DB_PATH, 'w') as f:
        json.dump(db, f, indent=2)

def download_file(url, filepath):
    print(f"Downloading {url}...")
    response = requests.get(url, stream=True)
    total_size = int(response.headers.get('content-length', 0))
    block_size = 8192
    
    with open(filepath, 'wb') as f:
        with tqdm(total=total_size, unit='iB', unit_scale=True, desc="Downloading") as pbar:
            for chunk in response.iter_content(chunk_size=block_size):
                if chunk:
                    f.write(chunk)
                    pbar.update(len(chunk))
    return filepath

def upload_to_gemini(path):
    """Uploads file to Gemini File API and waits for processing."""
    print(f"Uploading {path} to Gemini...")
    file = client.files.upload(file=path)
    print(f"Uploaded file '{file.display_name}' as: {file.uri}")
    
    # Wait for processing
    print("Waiting for file processing...")
    while file.state == "PROCESSING":
        time.sleep(2)
        file = client.files.get(name=file.name)
        
    if file.state != "ACTIVE":
        raise Exception(f"File upload failed with state: {file.state}")
        
    print("File is ready.")
    return file

def process_with_gemini(audio_file):
    """Sends the audio file to Gemini 1.5 Flash for transcription and formatting."""
    print("Requesting transcription from Gemini 1.5 Flash...")
    
    prompt = """
    You are a professional podcast transcriber and editor.
    
    Task:
    1. Listen to this audio file (it may be in Hebrew or English).
    2. Transcribe the conversation accurately.
    3. Identify the speakers by name (e.g., "Ran", "Shani") based on context.
    4. Keep primary language (Hebrew) as is.
    5. Format the output as a JSON list of segments.
    6. Group consecutive sentences by the same speaker into a single paragraph.
    
    Output Format (JSON):
    [
      {
        "speaker": "Speaker Name",
        "timestamp": "MM:SS",
        "text": "The full text of what they said..."
      },
      ...
    ]
    
    IMPORTANT: Return ONLY the JSON. No markdown formatting, no code blocks.
    """
    
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=[audio_file, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        )
    )
    
    try:
        return json.loads(response.text)
    except Exception as e:
        print(f"Failed to parse JSON response: {e}")
        print("Raw response:", response.text[:500])
        return []

def render_html(template_name, context, output_path):
    env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates')))
    template = env.get_template(template_name)
    content = template.render(context)
    with open(output_path, 'w') as f:
        f.write(content)

def git_sync(processed_ids):
    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
    if not status:
        return

    print("Syncing with Git...")
    try:
        subprocess.run(["git", "add", "docs/", "db.json"], check=True)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        subprocess.run(["git", "commit", "-m", f"Update transcripts: {timestamp}"], check=True)
        subprocess.run(["git", "push"], capture_output=True, check=True)
        print("Successfully pushed to GitHub.")
    except subprocess.CalledProcessError as e:
        print(f"Git Error: {e}")

def main():
    if not client:
        return
        
    config = load_config()
    db = load_db()
    processed_ids = set(db['processed'])
    
    for feed_conf in config['feeds']:
        print(f"Checking feed: {feed_conf['name']}")
        d = feedparser.parse(feed_conf['url'])
        
        # Default image
        feed_image = d.feed.get('image', {}).get('href') or d.feed.get('itunes_image')
        
        for entry in d.entries[:3]: # Check latest 3 episodes
            guid = entry.id
            if guid in processed_ids:
                continue
                
            print(f"Found new episode: {entry.title}")
            
            # Find audio URL
            audio_url = None
            for link in entry.links:
                if link.type == 'audio/mpeg':
                    audio_url = link.href
                    break
            
            if not audio_url:
                continue

            slug = slugify(entry.title)
            temp_mp3 = os.path.join(TEMP_DIR, f"{slug}.mp3")
            
            try:
                # 1. Download
                download_file(audio_url, temp_mp3)
                
                # 2. Upload to Gemini
                gemini_file = upload_to_gemini(temp_mp3)
                
                # 3. Transcribe
                segments = process_with_gemini(gemini_file)
                
                # 4. Cleanup Gemini File
                client.files.delete(name=gemini_file.name)
                
                if not segments:
                    print("Error: No transcript generated.")
                    continue

                # 5. Build HTML
                episode_data = {
                    "title": entry.title,
                    "published": entry.published,
                    "audio_url": audio_url,
                    "slug": slug,
                    "feed_name": feed_conf['name'],
                    "feed_image": feed_image
                }
                
                for seg in segments:
                    seg['start_fmt'] = seg.get('timestamp', '')

                render_html('episode.html', 
                           {"episode": episode_data, "segments": segments}, 
                           os.path.join(EPISODES_DIR, f"{slug}.html"))
                
                # 6. Update DB
                db['processed'].append(guid)
                db['episodes'].insert(0, {
                    "title": entry.title,
                    "published_date": entry.published,
                    "slug": slug,
                    "feed_name": feed_conf['name'],
                    "feed_image": feed_image
                })
                save_db(db)
                print(f"Successfully processed: {entry.title}")
                
                # 7. Sync
                render_html('index.html', {"site": config['site_settings'], "episodes": db['episodes']}, os.path.join(OUTPUT_DIR, 'index.html'))
                rss_context = {
                    "site": config['site_settings'],
                    "episodes": db['episodes'][:20],
                    "build_date": formatdate()
                }
                render_html('rss.xml', rss_context, os.path.join(OUTPUT_DIR, 'rss.xml'))
                
                import shutil
                shutil.copy(os.path.join(os.path.dirname(__file__), 'templates', 'styles.css'), os.path.join(OUTPUT_DIR, 'styles.css'))
                
                git_sync(db['processed'])

            except Exception as e:
                print(f"Error processing {entry.title}: {e}")
            
            finally:
                if os.path.exists(temp_mp3):
                    os.remove(temp_mp3)

if __name__ == "__main__":
    main()
