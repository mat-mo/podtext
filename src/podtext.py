import os
import json
import time
import datetime
import requests
import yaml
import feedparser
import subprocess
import re
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
    print("Requesting transcription from Gemini 3 Flash Preview...")
    
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
    {
      "language": "he" or "en",
      "segments": [
        {
          "speaker": "Speaker Name",
          "timestamp": "MM:SS",
          "text": "The full text..."
        }
      ]
    }
    
    IMPORTANT: Return ONLY the valid JSON object. Ensure all strings are properly escaped.
    """
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-3-flash-preview",
                contents=[audio_file, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                )
            )
            
            data = json.loads(response.text)
            # Handle both old (list) and new (dict) formats for robustness
            if isinstance(data, list):
                return {"language": "en", "segments": data}
            return data
            
        except json.JSONDecodeError as e:
            print(f"JSON Parse Error (Attempt {attempt+1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                print("Raw response:", response.text[:500])
                raise Exception(f"Gemini API Error or Parse Failure: {e}")
            time.sleep(2) # Wait a bit before retry
            
        except Exception as e:
            print(f"API Error (Attempt {attempt+1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                raise e
            time.sleep(5)

def get_episode_content(episode_data):
    """Reads the generated HTML file and extracts the transcript part for RSS."""
    try:
        # Construct path: docs/episodes/feed_slug/slug.html
        path = os.path.join(EPISODES_DIR, episode_data['feed_slug'], f"{episode_data['slug']}.html")
        if not os.path.exists(path):
            return "Transcript not available."
            
        with open(path, 'r') as f:
            html = f.read()
            
        # Extract content inside transcript container
        # Pattern: <div class="transcript-container" id="transcript"> ... </div>
        # Use regex to be robust against whitespace
        match = re.search(r'<div class="transcript-container" id="transcript">(.*?)</div>\s*</body>', html, re.DOTALL)
        if match:
            # We found the container. 
            # Note: The container closing tag might be hard to find if nested divs exist (like .paragraph).
            # A simpler regex might be better if we assume structure.
            # Let's try to extract everything between the start of container and the end of file (minus footer)
            content = match.group(1)
            return content
        else:
            # Fallback: return body
            return html
    except Exception as e:
        print(f"Error reading content for RSS: {e}")
        return "Error loading transcript."

def render_html(template_name, context, output_path):
    env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates')))
    template = env.get_template(template_name)
    content = template.render(context)
    with open(output_path, 'w') as f:
        f.write(content)

def git_sync(processed_ids, episode_title=None):
    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
    if not status:
        return

    print("Syncing with Git...")
    try:
        subprocess.run(["git", "add", "docs/", "db.json"], check=True)
        if episode_title:
            message = f'New transcript for "{episode_title}"'
        else:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            message = f"Update transcripts: {timestamp}"
            
        subprocess.run(["git", "commit", "-m", message], check=True)
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
        
        for entry in d.entries[:200]: # Check latest 200 episodes
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
            feed_slug = slugify(feed_conf['name'])
            feed_dir = os.path.join(EPISODES_DIR, feed_slug)
            os.makedirs(feed_dir, exist_ok=True)
            
            temp_mp3 = os.path.join(TEMP_DIR, f"{slug}.mp3")
            
            try:
                # 1. Download
                download_file(audio_url, temp_mp3)
                
                # 2. Upload to Gemini
                gemini_file = upload_to_gemini(temp_mp3)
                
                # 3. Transcribe
                result = process_with_gemini(gemini_file)
                segments = result.get('segments', [])
                lang_code = result.get('language', 'en')
                direction = "rtl" if lang_code == 'he' else "ltr"
                
                # 4. Cleanup Gemini File
                client.files.delete(name=gemini_file.name)
                
                if not segments:
                    raise Exception("Error: No transcript generated (Empty segments).")

                # 5. Build HTML
                episode_data = {
                    "title": entry.title,
                    "published": entry.published,
                    "audio_url": audio_url,
                    "slug": slug,
                    "feed_name": feed_conf['name'],
                    "feed_slug": feed_slug,
                    "feed_image": feed_image,
                    "css_path": "../../styles.css",
                    "home_path": "../../index.html"
                }
                
                for seg in segments:
                    seg['start_fmt'] = seg.get('timestamp', '')

                output_html_path = os.path.join(feed_dir, f"{slug}.html")
                render_html('episode.html', 
                           {"episode": episode_data, "segments": segments, "direction": direction}, 
                           output_html_path)
                           
                # Validate Output
                if not os.path.exists(output_html_path) or os.path.getsize(output_html_path) < 500:
                    raise Exception("Generated HTML is missing or too small (transcription likely failed).")
                
                # 6. Update DB (Only after success verification)
                db['processed'].append(guid)
                db['episodes'].insert(0, {
                    "title": entry.title,
                    "published_date": entry.published,
                    "slug": slug,
                    "feed_name": feed_conf['name'],
                    "feed_slug": feed_slug,
                    "feed_image": feed_image
                })
                save_db(db)
                print(f"Successfully processed: {entry.title}")
                
                # 7. Sync
                render_html('index.html', {"site": config['site_settings'], "episodes": db['episodes']}, os.path.join(OUTPUT_DIR, 'index.html'))
                # Generate RSS Feed
                # Populate content for the latest 20 episodes
                rss_episodes = db['episodes'][:20]
                for ep in rss_episodes:
                    # Only load if not already present (optimization if running in loop)
                    if 'content' not in ep:
                        ep['content'] = get_episode_content(ep)

                rss_context = {
                    "site": config['site_settings'],
                    "episodes": rss_episodes, # Include last 20 episodes in feed
                    "build_date": formatdate()
                }
                render_html('rss.xml', rss_context, os.path.join(OUTPUT_DIR, 'rss.xml'))

                
                import shutil
                shutil.copy(os.path.join(os.path.dirname(__file__), 'templates', 'styles.css'), os.path.join(OUTPUT_DIR, 'styles.css'))
                
                git_sync(db['processed'], episode_title=entry.title)

            finally:
                # Cleanup Temp
                if os.path.exists(temp_mp3):
                    os.remove(temp_mp3)

if __name__ == "__main__":
    main()
