# Podtext

Podtext is an automated podcast-to-text pipeline. It downloads podcast episodes from RSS feeds, transcribes them locally using OpenAI's Whisper (optimized for Apple Silicon), and generates a static website where the transcript is synchronized with the audio.

It is designed to be self-hosted on your local machine, pushing the generated HTML directly to GitHub Pages.

## Features

*   **Local Transcription:** Uses `faster-whisper` for high-performance offline transcription.
*   **Apple Silicon Optimized:** Runs efficiently on M1/M2/M3/M4 chips using INT8 quantization on the CPU/Neural Engine.
*   **Interactive Player:** Click any word in the transcript to jump to that point in the audio; audio playback highlights words in real-time.
*   **Git Sync:** Automatically commits and pushes new episodes to GitHub.
*   **RSS Feed:** Generates a custom RSS feed (`rss.xml`) for your transcripts.
*   **Storage Efficient:** Only stores text and HTML. Audio is hotlinked from the original podcast source.

## Prerequisites

*   **Python 3.10 - 3.12** (Python 3.14 is not yet supported by some audio libraries)
*   **macOS** (Optimized for, but runs on Linux/Windows with adjustments)
*   **ffmpeg** (Required for audio processing: `brew install ffmpeg`)

## Installation

1.  **Clone the repository:**
    ```bash
    git clone git@github.com:mat-mo/podtext.git
    cd podtext
    ```

2.  **Set up the Virtual Environment:**
    ```bash
    python3.12 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

3.  **Configuration:**
    Edit `config.yaml` to add your podcasts and site settings:
    ```yaml
    feeds:
      - url: "https://feeds.simplecast.com/your-feed"
        name: "Podcast Name"
    
    site_settings:
      title: "My Transcripts"
      base_url: "https://mat-mo.github.io/podtext"
    ```

## Usage

### Manual Run
Run the script to check for new episodes and process them:

```bash
source venv/bin/activate
python src/podtext.py
```

### Automatic Updates (Cron)
To keep your site up-to-date automatically, add a cron job.
Run `crontab -e` and add:

```bash
# Run every hour at minute 0
0 * * * * cd /Users/matanya/git-repos/podtext && venv/bin/python src/podtext.py >> run.log 2>&1
```

## Hosting (GitHub Pages)

1.  Push this repo to GitHub.
2.  Go to **Settings > Pages**.
3.  Under **Build and deployment**:
    *   **Source:** Deploy from a branch
    *   **Branch:** `main`
    *   **Folder:** `/docs` (IMPORTANT: Do not select /root)
4.  Your site will be live at `https://mat-mo.github.io/podtext/`.

## License

MIT
