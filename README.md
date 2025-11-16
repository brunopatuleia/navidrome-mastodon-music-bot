# Navidrome to Mastodon Music Bot

A bot that automatically posts to Mastodon whenever you favorite a song in Navidrome.

## What it does

Whenever you star/favorite a song in Navidrome, this bot will automatically create a Mastodon post with:

- `#NowPlaying` hashtag
- Artist and track name
- Up to 3 genre hashtags
- Album cover art

**Example post:**
```
#NowPlaying

Pink Floyd - Comfortably Numb

#ProgressiveRock #Rock #ClassicRock

[Album cover image attached]
```

## Features

- Monitors Navidrome for newly starred/favorited songs
- Posts immediately when you favorite a track
- Tracks which songs have been posted to avoid duplicates
- Persists state across restarts (using `posted_songs.json`)
- Handles genre formatting (removes spaces and hyphens for hashtags)
- Downloads and attaches album artwork
- Robust error handling and logging

## Setup

### 1. Create secrets file

Copy the example configuration:
```bash
cp secrets_example.py secrets.py
```

### 2. Configure secrets.py

Edit `secrets.py` with your settings:

```python
# Mastodon configuration
MASTODON_API_BASE_URL = "https://mastodon.social"  # Your Mastodon instance
MASTODON_ACCESS_TOKEN = "your_token_here"  # Get from Settings > Development

# Navidrome configuration
NAVIDROME_BASE_URL = "http://localhost:4533"  # Your Navidrome server
NAVIDROME_USER = "your_username"
NAVIDROME_PASSWORD = "your_password"

# Bot configuration
CHECK_INTERVAL_SECONDS = 30  # How often to check for new favorites
```

#### Getting a Mastodon Access Token

1. Go to your Mastodon instance Settings
2. Navigate to Development → New Application
3. Give it a name (e.g., "Navidrome Music Bot")
4. Required scopes: `write:statuses` and `write:media`
5. Save and copy the access token

### 3. Run with Docker

Build the Docker image:
```bash
docker build -t navidrome-mastodon-bot -f Dockerfile.dockerfile .
```

Run the container:
```bash
docker run -d \
  --restart always \
  --name navidrome-mastodon-bot \
  -v $(pwd)/posted_songs.json:/app/posted_songs.json \
  navidrome-mastodon-bot
```

Or run directly with Python:
```bash
pip install requests
python main.py
```

## How it works

1. The bot polls Navidrome's `getStarred2` API endpoint at regular intervals
2. It compares the list of starred songs with previously posted songs (stored in `posted_songs.json`)
3. When a new favorite is detected:
   - Downloads the album cover art
   - Uploads it to Mastodon
   - Creates a formatted post with artist, track, and genre hashtags
   - Saves the song ID to avoid duplicate posts
4. The process repeats every `CHECK_INTERVAL_SECONDS`

## Persistence

The bot maintains a `posted_songs.json` file to track which songs have already been posted. This ensures:
- No duplicate posts when restarting the bot
- You can safely stop and start the bot without re-posting all your favorites

## Troubleshooting

### Bot doesn't post anything
- Check that you have starred songs in Navidrome
- Verify your Mastodon token has `write:statuses` and `write:media` permissions
- Check the console output for error messages

### Connection errors
- Ensure Navidrome is running and accessible at the configured URL
- Verify your Navidrome credentials are correct
- Check that your Mastodon instance URL is correct

### Posts missing genres
- Not all songs have genre metadata
- The bot will post without genres if none are available
- Ensure your music files have proper ID3 tags

## Requirements

- Python 3.9+
- `requests` library
- A running Navidrome server
- A Mastodon account

## License

MIT License - feel free to modify and use as you wish!
