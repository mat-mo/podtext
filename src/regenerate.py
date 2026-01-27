import os
import json
import yaml
import re
from jinja2 import Environment, FileSystemLoader
from email.utils import formatdate
from slugify import slugify
from datetime import datetime
import time

HEBREW_MONTHS = [
    "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
    "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"
]

def format_hebrew_date(date_str):
    """Converts a date string (English) to Hebrew format."""
    if not date_str: return ""
    # If already Hebrew (contains Hebrew chars), return as is
    if any("\u0590" <= c <= "\u05EA" for c in date_str):
        return date_str
        
    try:
        # Try parsing standard RSS format "Mon, 12 Jan 2026 15:09:30 +0000"
        dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
        return f"{dt.day} ב{HEBREW_MONTHS[dt.month-1]} {dt.year}"
    except:
        return date_str

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.yaml')
DB_PATH = os.path.join(BASE_DIR, 'db.json')
OUTPUT_DIR = os.path.join(BASE_DIR, 'docs')
EPISODES_DIR = os.path.join(OUTPUT_DIR, 'episodes')
PODCASTS_DIR = os.path.join(OUTPUT_DIR, 'podcasts')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

def load_db():
    if os.path.exists(DB_PATH):
        with open(DB_PATH, 'r') as f:
            return json.load(f)
    return {"processed": [], "episodes": []}

def get_episode_content(episode_data):
    try:
        path = os.path.join(EPISODES_DIR, episode_data['feed_slug'], f"{episode_data['slug']}.html")
        if not os.path.exists(path): return ""
        with open(path, 'r') as f: html = f.read()
        match = re.search(r'<div class="transcript-container" id="transcript">(.*?)</div>\s*<script>', html, re.DOTALL)
        if match:
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

def main():
    print("Regenerating complete site structure...")
    config = load_config()
    db = load_db()
    
    # Ensure dirs
    os.makedirs(PODCASTS_DIR, exist_ok=True)

    # 1. Recent Episodes (Index)
    recent = db['episodes'][:20]
    for ep in recent:
        ep['published_date'] = format_hebrew_date(ep.get('published_date', ''))
        
    render_html('index.html', 
               {"site": config['site_settings'], "episodes": recent, "relative_path": ""}, 
               os.path.join(OUTPUT_DIR, 'index.html'))

    # 2. Podcasts Page
    podcasts_data = {}
    for ep in db['episodes']:
        ep['published_date'] = format_hebrew_date(ep.get('published_date', ''))
        
        feed_slug = ep.get('feed_slug', slugify(ep['feed_name']))
        if feed_slug not in podcasts_data:
            podcasts_data[feed_slug] = {
                "name": ep['feed_name'],
                "slug": feed_slug,
                "image": ep.get('feed_image'),
                "episodes": [],
                "count": 0,
                # Simple lookup for source URL
                "source_url": next((f['url'] for f in config['feeds'] if slugify(f['name']) == feed_slug), "#")
            }
        podcasts_data[feed_slug]['episodes'].append(ep)
        podcasts_data[feed_slug]['count'] += 1

    render_html('podcasts.html', 
               {"site": config['site_settings'], "podcasts": podcasts_data, "relative_path": ""}, 
               os.path.join(OUTPUT_DIR, 'podcasts.html'))

    # 3. Individual Podcast Pages
    for feed_slug, data in podcasts_data.items():
        render_html('podcast.html', 
                   {"site": config['site_settings'], "feed": data, "episodes": data['episodes'], "relative_path": "../"}, 
                   os.path.join(PODCASTS_DIR, f"{feed_slug}.html"))

    # 4. Search Index
    print("Building search index...")
    search_index = []
    for ep in db['episodes'][:50]: # Limit to recent 50 for performance
        text = get_episode_content(ep)
        search_index.append({
            "title": ep['title'],
            "feed": ep['feed_name'],
            "url": f"episodes/{ep['feed_slug']}/{ep['slug']}.html",
            "text": text[:1000]
        })
    with open(os.path.join(OUTPUT_DIR, 'search.json'), 'w') as f:
        json.dump(search_index, f)

    # 5. RSS
    for ep in recent:
        if 'content' not in ep: ep['content'] = get_episode_content(ep)
    
    rss_context = {"site": config['site_settings'], "episodes": recent, "build_date": formatdate()}
    render_html('rss.xml', rss_context, os.path.join(OUTPUT_DIR, 'rss.xml'))

    # 6. Assets
    import shutil
    shutil.copy(os.path.join(os.path.dirname(__file__), 'templates', 'styles.css'), os.path.join(OUTPUT_DIR, 'styles.css'))
    shutil.copy(os.path.join(os.path.dirname(__file__), 'templates', 'search.js'), os.path.join(OUTPUT_DIR, 'search.js'))
    
    # 7. Regenerate Episode Pages (to update header/footer/date format)
    print("Regenerating episode pages...")
    for ep in db['episodes']:
        feed_slug = ep.get('feed_slug', slugify(ep['feed_name']))
        path = os.path.join(EPISODES_DIR, feed_slug, f"{ep['slug']}.html")
        
        if os.path.exists(path):
            with open(path, 'r') as f: html = f.read()
            # Extract inner HTML of transcript container to preserve paragraphs
            match = re.search(r'<div class="transcript-container" id="transcript">\s*(.*?)\s*</div>\s*<script>', html, re.DOTALL)
            if match:
                transcript_html = match.group(1)
                
                # Update context
                ep_context = ep.copy()
                # Ensure published_date is Hebrew (it was updated in the loop above)
                ep_context['published_date'] = ep['published_date']
                
                render_html('episode.html', 
                           {"site": config['site_settings'], "episode": ep_context, "transcript_html": transcript_html, "direction": "rtl", "relative_path": "../../"}, 
                           path)

    print("Done!")

if __name__ == "__main__":
    main()