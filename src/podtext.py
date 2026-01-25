import os
import json
import time
import datetime
import requests
import yaml
import feedparser
import subprocess
from email.utils import formatdate
from slugify import slugify
from jinja2 import Environment, FileSystemLoader
from faster_whisper import WhisperModel

# Configuration Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.yaml')
DB_PATH = os.path.join(BASE_DIR, 'db.json')
OUTPUT_DIR = os.path.join(BASE_DIR, 'docs')
EPISODES_DIR = os.path.join(OUTPUT_DIR, 'episodes')
TEMP_DIR = os.path.join(BASE_DIR, 'tmp')

# Ensure directories exist
for d in [OUTPUT_DIR, EPISODES_DIR, TEMP_DIR]:
    os.makedirs(d, exist_ok=True)

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
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(filepath, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    return filepath

def format_timestamp(seconds):
    """Converts seconds (float) to MM:SS string."""
    seconds = int(seconds)
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes:02}:{secs:02}"

def transcribe_audio(model, audio_path):
    print(f"Transcribing {audio_path}...")
    # Run on CPU with INT8 quantization (fast and efficient on M-series chips)
    segments, info = model.transcribe(audio_path, word_timestamps=True)
    
    results = []
    for segment in segments:
        words = []
        for word in segment.words:
            words.append({
                "word": word.word,
                "start": word.start,
                "end": word.end
            })
        
        results.append({
            "start": segment.start,
            "end": segment.end,
            "start_fmt": format_timestamp(segment.start),
            "text": segment.text,
            "words": words
        })
    return results

def render_html(template_name, context, output_path):
    env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates')))
    template = env.get_template(template_name)
    content = template.render(context)
    with open(output_path, 'w') as f:
        f.write(content)

def main():
    config = load_config()
    db = load_db()
    
    # Initialize Whisper Model (Small is a good balance of speed/accuracy for English)
    # Use "medium" or "large-v3" for better accuracy if M4 can handle the speed hit.
    # We'll start with "small".
    print("Loading Whisper model...")
    model = WhisperModel("small", device="cpu", compute_type="int8")

    processed_ids = set(db['processed'])
    
    for feed_conf in config['feeds']:
        print(f"Checking feed: {feed_conf['name']}")
        d = feedparser.parse(feed_conf['url'])
        
        for entry in d.entries[:5]: # Check latest 5 episodes
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
                print("No audio URL found, skipping.")
                continue

            slug = slugify(entry.title)
            temp_mp3 = os.path.join(TEMP_DIR, f"{slug}.mp3")
            
            try:
                # 1. Download
                download_file(audio_url, temp_mp3)
                
                # 2. Transcribe
                segments = transcribe_audio(model, temp_mp3)
                
                # 3. Build Context
                episode_data = {
                    "title": entry.title,
                    "published": entry.published,
                    "audio_url": audio_url, # Hotlink original
                    "slug": slug,
                    "feed_name": feed_conf['name']
                }
                
                # 4. Generate HTML
                render_html('episode.html', 
                           {"episode": episode_data, "segments": segments}, 
                           os.path.join(EPISODES_DIR, f"{slug}.html"))
                
                # 5. Update DB
                db['processed'].append(guid)
                db['episodes'].insert(0, { # Prepend to keep newest first
                    "title": entry.title,
                    "published_date": entry.published, # Simple string for now
                    "slug": slug,
                    "feed_name": feed_conf['name']
                })
                save_db(db)
                
                print(f"Successfully processed: {entry.title}")

            except Exception as e:
                print(f"Error processing {entry.title}: {e}")
            
            finally:
                # Cleanup
                if os.path.exists(temp_mp3):
                    os.remove(temp_mp3)

    # Rebuild Index
    print("Rebuilding index...")
    render_html('index.html', {"site": config['site_settings'], "episodes": db['episodes']}, os.path.join(OUTPUT_DIR, 'index.html'))
    
    # Generate RSS Feed
    print("Generating RSS feed...")
    rss_context = {
        "site": config['site_settings'],
        "episodes": db['episodes'][:20], # Include last 20 episodes in feed
        "build_date": formatdate()
    }
    render_html('rss.xml', rss_context, os.path.join(OUTPUT_DIR, 'rss.xml'))

    # Copy CSS
    import shutil
    shutil.copy(os.path.join(os.path.dirname(__file__), 'templates', 'styles.css'), os.path.join(OUTPUT_DIR, 'styles.css'))

    # Git Sync
    git_sync(db['processed'])

def git_sync(processed_ids):
    """Commits and pushes changes if there are new items."""
    # Check for changes
    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
    if not status:
        print("No changes to commit.")
        return

    print("Syncing with Git...")
    try:
        subprocess.run(["git", "add", "docs/", "db.json"], check=True)
        # Using a generic message, but could be specific if we passed the new episode titles
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        subprocess.run(["git", "commit", "-m", f"Update transcripts: {timestamp}"], check=True)
        
        # Try to push, but don't crash if no remote is set
        result = subprocess.run(["git", "push"], capture_output=True, text=True)
        if result.returncode == 0:
            print("Successfully pushed to GitHub.")
        else:
            print(f"Git push failed (maybe no remote?): {result.stderr.strip()}")
            
    except subprocess.CalledProcessError as e:
        print(f"Git Error: {e}")

if __name__ == "__main__":
    main()
