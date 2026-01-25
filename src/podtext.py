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
from pyannote.audio import Pipeline
import torch
from dotenv import load_dotenv
import ollama

# Load environment variables from .env file
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

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

def transcribe_and_diarize(whisper_model, diarization_pipeline, audio_path):
    print(f"Transcribing {audio_path}...")
    # 1. Run Whisper
    segments, info = whisper_model.transcribe(audio_path, word_timestamps=True)
    
    whisper_words = []
    for segment in segments:
        for word in segment.words:
            whisper_words.append({
                "word": word.word,
                "start": word.start,
                "end": word.end
            })
            
    # 2. Run Diarization
    print("Running diarization (this may take a while)...")
    diarization = diarization_pipeline(audio_path)
    
    # 3. Align Words to Speakers
    final_segments = []
    current_segment = None
    
    for word in whisper_words:
        # Find speaker for this word
        # Simple strategy: Check which diarization turn covers the midpoint of the word
        word_mid = (word['start'] + word['end']) / 2
        speaker = "Unknown"
        
        # Iterate over turns to find the matching one
        # Optimization: Diarization turns are sorted, we could track index, but loop is fine for podcast length
        for turn, _, spk in diarization.itertracks(yield_label=True):
            if turn.start <= word_mid <= turn.end:
                speaker = spk
                break
        
        # Grouping Logic
        if current_segment and current_segment['speaker'] == speaker:
            # Append to current
            current_segment['words'].append(word)
            current_segment['end'] = word['end']
            current_segment['text'] += "" + word['word'] # Space handling might need improvement depending on Whisper output
        else:
            # New Segment
            if current_segment:
                final_segments.append(current_segment)
            
            current_segment = {
                "speaker": speaker,
                "start": word['start'],
                "end": word['end'],
                "start_fmt": format_timestamp(word['start']),
                "words": [word],
                "text": word['word']
            }
            
    if current_segment:
        final_segments.append(current_segment)
        
    return final_segments

def identify_speakers(segments):
    """Uses local LLM to map SPEAKER_XX to real names."""
    print("Identifying speakers with Llama 3.2...")
    
    # 1. Prepare Context (First ~2000 chars should contain intros)
    transcript_sample = ""
    for seg in segments[:20]: # Check first 20 segments
        transcript_sample += f"{seg['speaker']}: {seg['text']}\n"
        
    if len(transcript_sample) > 3000:
        transcript_sample = transcript_sample[:3000]
        
    prompt = f"""
    Read the following podcast transcript snippet and identify the real names of the speakers.
    Return ONLY a JSON object mapping the SPEAKER codes to their real names.
    If you cannot identify a speaker, do not include them.
    Example: {{"SPEAKER_00": "Michael Barbaro", "SPEAKER_01": "Sabrina Tavernise"}}
    
    Transcript:
    {transcript_sample}
    """
    
    try:
        response = ollama.chat(model='llama3.2', messages=[
            {'role': 'user', 'content': prompt},
        ], format='json')
        
        mapping = json.loads(response['message']['content'])
        print(f"Identified Speakers: {mapping}")
        
        # Apply mapping
        for seg in segments:
            if seg['speaker'] in mapping:
                seg['speaker'] = mapping[seg['speaker']]
                
    except Exception as e:
        print(f"Speaker identification failed: {e}")
        
    return segments

def render_html(template_name, context, output_path):
    env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates')))
    template = env.get_template(template_name)
    content = template.render(context)
    with open(output_path, 'w') as f:
        f.write(content)

def main():
    config = load_config()
    db = load_db()
    
    # Initialize Whisper Model
    print("Loading Whisper model...")
    model = WhisperModel("small", device="cpu", compute_type="int8")

    # Initialize Diarization Pipeline
    print("Loading Diarization pipeline...")
    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        print("Warning: HF_TOKEN not found. Diarization may fail.")
        
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf_token
    )
    # Check if Metal (MPS) is available for PyTorch (M-series GPU acceleration)
    # Pyannote uses Pytorch.
    if torch.backends.mps.is_available():
        print("Using MPS (Apple Silicon GPU) for Diarization")
        pipeline.to(torch.device("mps"))
    else:
        print("Using CPU for Diarization")

    processed_ids = set(db['processed'])
    
    for feed_conf in config['feeds']:
        print(f"Checking feed: {feed_conf['name']}")
        d = feedparser.parse(feed_conf['url'])
        
        # specific to simplecast/standard RSS
        feed_image = d.feed.get('image', {}).get('href') or d.feed.get('itunes_image')
        
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
                
                # 2. Transcribe & Diarize
                segments = transcribe_and_diarize(model, pipeline, temp_mp3)
                
                # 2.5 Identify Speakers (Local LLM)
                segments = identify_speakers(segments)
                
                # 3. Build Context
                episode_data = {
                    "title": entry.title,
                    "published": entry.published,
                    "audio_url": audio_url, # Hotlink original
                    "slug": slug,
                    "feed_name": feed_conf['name'],
                    "feed_image": feed_image
                }
                
                # 4. Generate HTML
                render_html('episode.html', 
                           {"episode": episode_data, "segments": segments}, 
                           os.path.join(EPISODES_DIR, f"{slug}.html"))
                
                # 5. Update DB
                db['processed'].append(guid)
                db['episodes'].insert(0, { # Prepend to keep newest first
                    "title": entry.title,
                    "published_date": entry.published,
                    "slug": slug,
                    "feed_name": feed_conf['name'],
                    "feed_image": feed_image
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
