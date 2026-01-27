# Podtext

Podtext is an automated, AI-powered podcast transcription pipeline. It listens to podcast RSS feeds, transcribes episodes using Google Gemini 1.5 Flash (Multimodal), and publishes a static website with the transcripts.

## Features

*   **AI Transcription:** Uses **Gemini 1.5 Flash** to transcribe, identify speakers, and format text in one pass.
*   **Multilingual:** Native support for Hebrew and English (auto-detected).
*   **Book-Style Layout:** Transcripts are formatted as readable paragraphs, not chat logs.
*   **RTL Support:** Automatic Right-to-Left layout for Hebrew content.
*   **Search:** Built-in full-text search across all episodes.
*   **Podcast Library:** Organizes episodes by podcast feed.
*   **Dark Mode:** Auto-switching based on system preference.
*   **RSS Feed:** Generates a full-text RSS feed of the transcripts.
*   **Git Sync:** Automatically pushes updates to GitHub Pages.

## Architecture

1.  **`podtext.py`**: The main engine.
    *   Checks RSS feeds for new episodes.
    *   Downloads MP3s.
    *   Uploads to Gemini API.
    *   Generates HTML pages and updates `db.json`.
    *   Syncs to GitHub.
2.  **`regenerate.py`**: Rebuilds the static site (`index.html`, `podcasts.html`, RSS, Search Index) from the database without re-processing audio.
3.  **`docs/`**: The output directory (GitHub Pages root).
    *   `episodes/<feed_slug>/`: Individual transcript files.
    *   `podcasts/`: Podcast profile pages.
    *   `search.json`: Index for the search bar.

## Setup

1.  **Install Dependencies:**
    ```bash
    python3.12 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

2.  **Environment:**
    Create a `.env` file with your Google Gemini API key:
    ```
    GEMINI_API_KEY=your_key_here
    ```

3.  **Config:**
    Edit `config.yaml` to add podcasts:
    ```yaml
    feeds:
      - url: "https://rss.url/..."
        name: "Podcast Name"
    site_settings:
      title: "Podtext"
      base_url: "https://your.site"
    ```

## Usage

**Process New Episodes:**
```bash
python src/podtext.py
```

**Rebuild Website (Design changes):**
```bash
python src/regenerate.py
```

## License
MIT