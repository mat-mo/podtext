import feedparser
import os
import yaml

# Load config to get the URL
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.yaml')

with open(CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f)

for feed_conf in config['feeds']:
    url = feed_conf['url']
    print(f"Checking URL: {url}")
    d = feedparser.parse(url)
    print(f"Feed Title: {d.feed.get('title', 'Unknown')}")
    print(f"Entries found: {len(d.entries)}")
    
    for i, entry in enumerate(d.entries[:5]):
        print(f"[{i}] {entry.title} (ID: {entry.id})")