import os
import json
import time
import requests
import yaml
import feedparser
import subprocess
import re
from datetime import datetime
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
PODCASTS_DIR = os.path.join(OUTPUT_DIR, 'podcasts')
TEMP_DIR = os.path.join(BASE_DIR, 'tmp')

# Ensure directories
for d in [OUTPUT_DIR, EPISODES_DIR, PODCASTS_DIR, TEMP_DIR]:
    os.makedirs(d, exist_ok=True)

HEBREW_MONTHS = [
    "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
    "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"
]

def format_hebrew_date(date_obj):
    """Converts a date object/string to Hebrew format (12 בינואר 2025)."""
    if not date_obj: return ""
    try:
        # feedparser returns struct_time
        if isinstance(date_obj, time.struct_time):
            dt = datetime.fromtimestamp(time.mktime(date_obj))
        elif isinstance(date_obj, str):
            # Try parsing standard RSS format
            dt = datetime.strptime(date_obj, "%a, %d %b %Y %H:%M:%S %z")
        else:
            return str(date_obj)
            
        return f"{dt.day} ב{HEBREW_MONTHS[dt.month-1]} {dt.year}"
    except Exception as e:
        return str(date_obj)

# Configure Gemini
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

def load_db():
    if os.path.exists(DB_PATH):
        with open(DB_PATH, 'r') as f:
            data = json.load(f)
            if "failed" not in data: data["failed"] = []
            return data
    return {"processed": [], "episodes": [], "failed": []}

def save_db(db):
    with open(DB_PATH, 'w') as f:
        json.dump(db, f, indent=2)

def get_episode_content(episode_data):
    try:
        path = os.path.join(EPISODES_DIR, episode_data['feed_slug'], f"{episode_data['slug']}.html")
        if not os.path.exists(path): return ""
        with open(path, 'r') as f:
            html = f.read()
        match = re.search(r'<div class="transcript-container" id="transcript">(.*?)</div>\s*<script>', html, re.DOTALL)
        if match:
            # Strip tags for search index text
            text = re.sub('<[^<]+?>', ' ', match.group(1))
            return re.sub('\s+', ' ', text).strip()
        return ""
    except: return ""

def render_html(template_name, context, output_path):
    env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates')))
    template = env.get_template(template_name)
    content = template.render(context)
    with open(output_path, 'w') as f:
        f.write(content)

def generate_site(db, config):
    """Regenerates all site pages (Index, Podcasts, Search, RSS)."""
    print("Regenerating site structure...")
    
    # 1. Recent Episodes (Index)
    # Sort by date (assuming published_date is sortable or we trust order)
    # For simplicity, we trust the DB order (newest first)
    recent_episodes = db['episodes'][:20]
    render_html('index.html', 
               {"site": config['site_settings'], "episodes": recent_episodes, "relative_path": ""}, 
               os.path.join(OUTPUT_DIR, 'index.html'))

    # 2. Podcasts Page & Individual Podcast Pages
    podcasts_data = {}
    
    # Group episodes by feed
    for ep in db['episodes']:
        feed_slug = ep.get('feed_slug', 'unknown')
        if feed_slug not in podcasts_data:
            podcasts_data[feed_slug] = {
                "name": ep['feed_name'],
                "slug": feed_slug,
                "image": ep.get('feed_image'),
                "episodes": [],
                "count": 0,
                # Find RSS url from config
                "rss_url": next((f['url'] for f in config['feeds'] if slugify(f['name']) == feed_slug), "#"),
                "source_url": next((f['url'] for f in config['feeds'] if slugify(f['name']) == feed_slug), "#")
            }
        podcasts_data[feed_slug]['episodes'].append(ep)
        podcasts_data[feed_slug]['count'] += 1

    # Render "All Podcasts" list
    render_html('podcasts.html', 
               {"site": config['site_settings'], "podcasts": podcasts_data, "relative_path": ""}, 
               os.path.join(OUTPUT_DIR, 'podcasts.html'))

    # Render Individual Podcast Pages
    for feed_slug, data in podcasts_data.items():
        render_html('podcast.html', 
                   {"site": config['site_settings'], "feed": data, "episodes": data['episodes'], "relative_path": "../"}, 
                   os.path.join(PODCASTS_DIR, f"{feed_slug}.html"))

    # 3. Search Index (JSON)
    print("Building search index...")
    search_index = []
    # Index recent 50 episodes to keep size manageable, or all if small
    for ep in db['episodes']:
        content_text = get_episode_content(ep)
        search_index.append({
            "title": ep['title'],
            "feed": ep['feed_name'],
            "url": f"episodes/{ep['feed_slug']}/{ep['slug']}.html",
            "text": content_text[:1000] # Index first 1000 chars for snippet
        })
    
    with open(os.path.join(OUTPUT_DIR, 'search.json'), 'w') as f:
        json.dump(search_index, f)

    # 4. RSS Feed
    rss_context = {
        "site": config['site_settings'],
        "episodes": recent_episodes,
        "build_date": formatdate()
    }
    # Hack: Add content for RSS
    for ep in rss_context['episodes']:
        if 'content' not in ep: ep['content'] = get_episode_content(ep)
        
    render_html('rss.xml', rss_context, os.path.join(OUTPUT_DIR, 'rss.xml'))

    # 5. Copy Assets
    import shutil
    shutil.copy(os.path.join(os.path.dirname(__file__), 'templates', 'styles.css'), os.path.join(OUTPUT_DIR, 'styles.css'))
    shutil.copy(os.path.join(os.path.dirname(__file__), 'templates', 'search.js'), os.path.join(OUTPUT_DIR, 'search.js'))

# ... (Keep existing download/upload/process functions) ...
# I need to re-implement them or just reference them if I could partial edit, 
# but I'm rewriting the file. I will paste the previous helper functions here.

def download_file(url, filepath):
    print(f"Downloading {url}...")
    response = requests.get(url, stream=True)
    total_size = int(response.headers.get('content-length', 0))
    with open(filepath, 'wb') as f:
        with tqdm(total=total_size, unit='iB', unit_scale=True, desc="Downloading") as pbar:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk: f.write(chunk); pbar.update(len(chunk))
    return filepath

def upload_to_gemini(path):
    print(f"Uploading {path} to Gemini...")
    file = client.files.upload(file=path)
    while file.state.name == "PROCESSING":
        time.sleep(2)
        file = client.files.get(name=file.name)
    if file.state.name != "ACTIVE": raise Exception(f"Upload failed: {file.state.name}")
    return file

def process_with_gemini(audio_file):
    prompt = """
    You are a professional podcast transcriber.
    Task: Transcribe accurately. Identify speakers. Keep original language (Hebrew).
    Format: JSON.
    Output Format: {"language": "he", "segments": [{"speaker": "Name", "timestamp": "MM:SS", "text": "..."}]}
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-3-flash-preview",
                contents=[audio_file, prompt],
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            text = response.text.strip()
            if text.startswith("```json"): text = text[7:-3]
            data = json.loads(text)
            if isinstance(data, list): return {"language": "en", "segments": data}
            return data
        except Exception:
            time.sleep(2)
    raise Exception("Gemini processing failed")

def git_sync(processed_ids, episode_title=None, file_path=None):
    if not subprocess.run(["git", "status", "--porcelain"], capture_output=True).stdout: return
    print("Syncing...")
    files = ["db.json", "docs/"]
    if file_path: files.append(file_path)
    subprocess.run(["git", "add"] + files, check=True)
    msg = f'New transcript: {episode_title}' if episode_title else f"Update site: {datetime.now()}"
    subprocess.run(["git", "commit", "-m", msg], check=True)
    subprocess.run(["git", "push"], check=True)

def main():
    if not client: return
    config = load_config()
    db = load_db()
    processed_ids = set(db['processed'])
    failed_ids = set(db.get('failed', []))
    
    for feed_conf in config['feeds']:
        d = feedparser.parse(feed_conf['url'])
        feed_image = d.feed.get('image', {}).get('href')
        
        for entry in d.entries[:200]:
            guid = entry.id
            slug = slugify(entry.title)
            feed_slug = slugify(feed_conf['name'])
            feed_dir = os.path.join(EPISODES_DIR, feed_slug)
            html_path = os.path.join(feed_dir, f"{slug}.html")
            
            if guid in processed_ids and os.path.exists(html_path): continue
            if guid in failed_ids: continue
            
            print(f"Processing: {entry.title}")
            # ... (Download/Process Logic) ...
            # For brevity in this rewrite, I'll paste the core logic back
            # Real implementation below:
            
            audio_url = next((l.href for l in entry.links if l.type == 'audio/mpeg'), None)
            if not audio_url: continue
            
            os.makedirs(feed_dir, exist_ok=True)
            temp_mp3 = os.path.join(TEMP_DIR, f"{slug}.mp3")
            
            try:
                download_file(audio_url, temp_mp3)
                gemini_file = upload_to_gemini(temp_mp3)
                result = process_with_gemini(gemini_file)
                client.files.delete(name=gemini_file.name)
                
                segments = result.get('segments', [])
                if not segments: raise Exception("Empty transcript")
                
                lang = result.get('language', 'en')
                direction = "rtl" if lang == 'he' else "ltr"
                
                # 5. Build HTML
                hebrew_date = format_hebrew_date(entry.published_parsed)
                
                episode_data = {
                    "title": entry.title,
                    "published_date": hebrew_date,
                    "audio_url": audio_url,
                    "slug": slug,
                    "feed_name": feed_conf['name'],
                    "feed_slug": feed_slug,
                    "feed_image": feed_image,
                    "css_path": "../../styles.css",
                    "home_path": "../../index.html"
                }
                
                for s in segments: s['start_fmt'] = s.get('timestamp', '')
                
                render_html('episode.html', 
                           {"episode": episode_data, "segments": segments, "direction": direction, "relative_path": "../../"}, 
                           html_path)
                
                if os.path.getsize(html_path) < 500: raise Exception("File too small")
                
                # 6. Update DB
                db['processed'].append(guid)
                db['episodes'].insert(0, {
                    "title": entry.title,
                    "published_date": hebrew_date,
                    "slug": slug,

                save_db(db)
                
                # Regenerate entire site structure
                generate_site(db, config)
                
                git_sync(db['processed'], entry.title, html_path)
                
            except Exception as e:
                print(f"Failed: {e}")
                db['failed'].append(guid)
                save_db(db)
            finally:
                if os.path.exists(temp_mp3): os.remove(temp_mp3)

if __name__ == "__main__":
    main()