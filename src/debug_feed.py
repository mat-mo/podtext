import feedparser

url = "https://www.osimhistoria.com/theanswer/podcast.xml"
print(f"Parsing {url}...")
d = feedparser.parse(url)

print(f"Feed Title: {d.feed.get('title', 'Unknown')}")
print(f"Number of entries: {len(d.entries)}")

if len(d.entries) > 0:
    entry = d.entries[0]
    print(f"\nLatest Entry: {entry.title}")
    print(f"ID: {entry.id}")
    print("Links:")
    for link in entry.links:
        print(f"  - Type: {link.type}, Href: {link.href}")
else:
    print("No entries found!")

