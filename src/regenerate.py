import os
import json
import yaml
import re
from jinja2 import Environment, FileSystemLoader
from email.utils import formatdate

# Configuration Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.yaml')
DB_PATH = os.path.join(BASE_DIR, 'db.json')
OUTPUT_DIR = os.path.join(BASE_DIR, 'docs')
EPISODES_DIR = os.path.join(OUTPUT_DIR, 'episodes')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

def load_db():
    if os.path.exists(DB_PATH):
        with open(DB_PATH, 'r') as f:
            return json.load(f)
    return {"processed": [], "episodes": []}

def get_episode_content(episode_data):
    """Reads the generated HTML file and extracts the transcript part for RSS."""
    try:
        path = os.path.join(EPISODES_DIR, episode_data['feed_slug'], f"{episode_data['slug']}.html")
        if not os.path.exists(path):
            return "Transcript not available."
            
        with open(path, 'r') as f:
            html = f.read()
            
        match = re.search(r'<div class="transcript-container" id="transcript">(.*?)</div>\s*</body>', html, re.DOTALL)
        if match:
            return match.group(1)
        else:
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

def main():
    print("Regenerating site index and RSS...")
    config = load_config()
    db = load_db()
    
    # Rebuild Index
    render_html('index.html', {"site": config['site_settings'], "episodes": db['episodes']}, os.path.join(OUTPUT_DIR, 'index.html'))
    
    # Generate RSS Feed
    rss_episodes = db['episodes'][:20]
    for ep in rss_episodes:
        ep['content'] = get_episode_content(ep)

    rss_context = {
        "site": config['site_settings'],
        "episodes": rss_episodes,
        "build_date": formatdate()
    }
    render_html('rss.xml', rss_context, os.path.join(OUTPUT_DIR, 'rss.xml'))
    
    # Copy CSS
    import shutil
    shutil.copy(os.path.join(os.path.dirname(__file__), 'templates', 'styles.css'), os.path.join(OUTPUT_DIR, 'styles.css'))
    
    print("Done!")

if __name__ == "__main__":
    main()
