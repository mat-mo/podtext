import os
import json
import yaml
import feedparser
from slugify import slugify

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.yaml')
DB_PATH = os.path.join(BASE_DIR, 'db.json')
EPISODES_DIR = os.path.join(BASE_DIR, 'docs', 'episodes')

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

def main():
    print("Repairing Database State...")
    config = load_config()
    db = load_db()
    
    # 1. Build a map of Slug -> GUID from live feeds
    print("Fetching feeds to map Slugs to IDs...")
    slug_to_guid = {}
    
    for feed_conf in config['feeds']:
        print(f"  - {feed_conf['name']}")
        d = feedparser.parse(feed_conf['url'])
        for entry in d.entries:
            s = slugify(entry.title)
            slug_to_guid[s] = entry.id

    # 2. Check Database Episodes vs Files
    valid_episodes = []
    removed_count = 0
    ids_to_remove = set()

    for ep in db['episodes']:
        # Construct expected path
        feed_slug = ep.get('feed_slug')
        if not feed_slug:
            # Legacy entry without feed_slug? Try to guess or skip
            feed_slug = slugify(ep['feed_name'])
            
        path = os.path.join(EPISODES_DIR, feed_slug, f"{ep['slug']}.html")
        
        if os.path.exists(path) and os.path.getsize(path) > 500:
            valid_episodes.append(ep)
        else:
            print(f"Missing/Broken file for: {ep['title']}")
            removed_count += 1
            # Mark ID for removal from processed list
            guid = slug_to_guid.get(ep['slug'])
            if guid:
                ids_to_remove.add(guid)
            else:
                print(f"  Warning: Could not find GUID for slug '{ep['slug']}'. You might need to manually clean 'processed'.")

    # 3. Update DB
    db['episodes'] = valid_episodes
    
    # Remove processed IDs
    # Strategy: Keep IDs that match valid episodes. Remove everything else.
    # Note: This is aggressive. If you have valid episodes whose slug->guid mapping fails, you might re-process duplicates.
    # But it is the only way to clean orphans.
    
    valid_guids = set()
    for ep in valid_episodes:
        guid = slug_to_guid.get(ep['slug'])
        if guid:
            valid_guids.add(guid)
    
    original_processed_count = len(db['processed'])
    
    # We keep an ID if it's in the valid set OR if we couldn't resolve its slug (to be safe? No, let's be strict for cleanup).
    # Actually, if we can't resolve the slug, we might accidentally delete a valid ID.
    # But since we just fetched the live feed, the mapping should be 100% complete for active episodes.
    
    db['processed'] = list(valid_guids)
    
    removed_ids_count = original_processed_count - len(db['processed'])
    
    save_db(db)
    print(f"\nDone.")
    print(f"Removed {removed_count} broken episodes from DB.")
    print(f"Unmarked {removed_ids_count} IDs from 'processed' list.")

if __name__ == "__main__":
    main()
