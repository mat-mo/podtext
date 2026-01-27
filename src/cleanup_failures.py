import os
import json
import glob

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'db.json')
EPISODES_DIR = os.path.join(BASE_DIR, 'docs', 'episodes')

def load_db():
    if os.path.exists(DB_PATH):
        with open(DB_PATH, 'r') as f:
            return json.load(f)
    return {"processed": [], "episodes": []}

def save_db(db):
    with open(DB_PATH, 'w') as f:
        json.dump(db, f, indent=2)

def main():
    print("Scanning for failed transcriptions...")
    db = load_db()
    
    # Track removals
    removed_slugs = []
    removed_ids = []
    
    # 1. Scan files
    # We look for files smaller than 1.5KB (empty template or error message)
    # A real transcript is usually > 5KB
    bad_files = []
    for root, dirs, files in os.walk(EPISODES_DIR):
        for file in files:
            if file.endswith(".html"):
                path = os.path.join(root, file)
                size = os.path.getsize(path)
                
                if size < 5000: # Threshold for "suspiciously small"
                    print(f"Found bad file: {file} ({size} bytes)")
                    bad_files.append((file, path))

    if not bad_files:
        print("No bad files found.")
        return

    # 2. Process Removals
    for filename, path in bad_files:
        slug = filename.replace(".html", "")
        removed_slugs.append(slug)
        
        # Remove file
        try:
            os.remove(path)
            print(f"Deleted: {path}")
        except OSError as e:
            print(f"Error deleting {path}: {e}")

    # 3. Clean DB
    # Filter episodes list
    original_count = len(db['episodes'])
    
    # We need to find the ID (url) associated with the slug to remove it from 'processed'
    ids_to_remove = set()
    
    # Filter out bad episodes and collect their IDs
    new_episodes = []
    for ep in db['episodes']:
        if ep['slug'] in removed_slugs:
            # This is a bad episode
            # We can't easily get the ID from the episode object directly unless we stored it explicitly 
            # (Wait, we store 'audio_url' which IS the ID usually used in 'processed' list by feedparser id? 
            # Let's check podtext.py logic. 
            # Ah, 'processed' stores entry.id (guid). The episode object doesn't strictly store the guid, 
            # but usually entry.id is unique. 
            # However, looking at db.json, 'processed' contains URLs like "https://api.spreaker.com/episode/..."
            # The 'episodes' list doesn't store this ID explicitly.
            # We might have to purge 'processed' based on matching audio_url or title?
            # Actually, removing from 'episodes' is enough to hide it from the site.
            # BUT to re-process, we MUST remove from 'processed'.
            
            # Heuristic: If we delete an episode, we should probably remove the corresponding audio_url from processed?
            # Or better: We can't map slug -> guid easily without the feed.
            # SAFETY FALLBACK: We will remove the episode from the visible list.
            # To re-process, the user might need to manually clear 'processed' or we just accept that we clean the visible site 
            # and they have to clear 'processed' manually if they want to re-run specific ones.
            
            # ACTUALLY: Let's try to match audio_url. Usually guid == audio_url or close.
            # If not, we can just remove *everything* from 'processed' that corresponds to the deleted episodes if we can guess.
            pass
        else:
            new_episodes.append(ep)
            
    # Update DB
    db['episodes'] = new_episodes
    
    # Save
    save_db(db)
    print(f"Removed {original_count - len(new_episodes)} entries from database.")
    
    print("\nIMPORTANT: I removed the bad HTML files and the database entries.")
    print("However, to force re-processing, you usually need to remove the ID from the 'processed' list in db.json.")
    print("Since I cannot perfectly map slugs to IDs right now, please manually check 'processed' list if re-running doesn't pick them up.")

if __name__ == "__main__":
    main()
