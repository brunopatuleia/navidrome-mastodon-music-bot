import requests
import time
import hashlib
import random
import string
import sys
import os
import json

# --- SCRIPT SETUP ---
# This is a special block to catch any error and print it, so the bot can't crash silently.
try:
    print("Mastodon Music Bot: Loading secrets...")
    from secrets import MASTODON_API_BASE_URL, MASTODON_ACCESS_TOKEN
    from secrets import NAVIDROME_BASE_URL, NAVIDROME_USER, NAVIDROME_PASSWORD
    from secrets import CHECK_INTERVAL_SECONDS
    print("Mastodon Music Bot: Secrets loaded successfully.")
except ImportError:
    print("CRITICAL ERROR: secrets.py file not found. Please ensure it exists.", file=sys.stderr)
    time.sleep(60)
    sys.exit(1)
except Exception as e:
    print(f"CRITICAL ERROR: Could not import from secrets.py. Check for syntax errors. Error: {e}", file=sys.stderr)
    time.sleep(60)
    sys.exit(1)


# --- CONSTANTS ---
POSTED_SONGS_FILE = "posted_songs.json"

# --- GLOBAL STATE ---
posted_song_ids = set()


# --- HELPER FUNCTIONS ---

def load_posted_songs():
    """Load the list of already posted song IDs from disk."""
    global posted_song_ids
    if os.path.exists(POSTED_SONGS_FILE):
        try:
            with open(POSTED_SONGS_FILE, 'r') as f:
                posted_song_ids = set(json.load(f))
            print(f"Loaded {len(posted_song_ids)} previously posted songs from {POSTED_SONGS_FILE}")
        except Exception as e:
            print(f"Error loading posted songs file: {e}. Starting with empty list.")
            posted_song_ids = set()
    else:
        print("No previous posted songs file found. Starting fresh.")
        posted_song_ids = set()


def save_posted_songs():
    """Save the list of posted song IDs to disk."""
    try:
        with open(POSTED_SONGS_FILE, 'w') as f:
            json.dump(list(posted_song_ids), f)
        print(f"Saved {len(posted_song_ids)} posted songs to {POSTED_SONGS_FILE}")
    except Exception as e:
        print(f"Error saving posted songs file: {e}")


def generate_salt():
    """Generates a random 6-character string for Subsonic API authentication."""
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(6))


def generate_token(password, salt):
    """Generates the required MD5 token for Subsonic API authentication."""
    return hashlib.md5((password + salt).encode('utf-8')).hexdigest()


def make_navidrome_request(endpoint, params=None):
    """A helper to make requests to the Navidrome (Subsonic) API."""
    if params is None:
        params = {}

    salt = generate_salt()
    token = generate_token(NAVIDROME_PASSWORD, salt)

    base_params = {
        "u": NAVIDROME_USER,
        "t": token,
        "s": salt,
        "v": "1.16.1",
        "c": "MastodonMusicBot/v3",
        "f": "json"
    }
    base_params.update(params)

    try:
        # Construct the URL carefully using os.path.join for reliability
        # This prevents issues with trailing slashes causing a 404 error.
        url = os.path.join(NAVIDROME_BASE_URL, "rest", endpoint)

        print(f"Navidrome Request: Contacting URL -> {url}")
        response = requests.get(url, params=base_params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "subsonic-response" in data and data["subsonic-response"]["status"] == "ok":
            return data["subsonic-response"]
        else:
            error = data.get("subsonic-response", {}).get("error", {})
            print(f"Navidrome API Error: Code {error.get('code', 'N/A')} - {error.get('message', 'Unknown error')}")
            return None
    except requests.exceptions.HTTPError as e:
        print(f"Navidrome Connection Error (HTTPError): The server responded with an error. Status Code: {e.response.status_code}. URL: {e.request.url}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Navidrome Connection Error (RequestException): Could not connect to the server. Is the URL correct and is Navidrome running? URL: {e.request.url if e.request else 'N/A'}")
        return None


def get_starred_songs():
    """Get all starred songs from Navidrome using the getStarred2 endpoint."""
    print("Fetching starred songs from Navidrome...")
    response = make_navidrome_request("getStarred2")

    if response and "starred2" in response:
        songs = response["starred2"].get("song", [])
        print(f"Found {len(songs)} starred songs in total.")
        return songs
    else:
        print("Could not get starred songs from Navidrome.")
        return []


def download_cover_art(cover_art_id):
    """Download album cover art from Navidrome."""
    cover_art_url = os.path.join(NAVIDROME_BASE_URL, "rest", "getCoverArt")
    salt = generate_salt()
    token = generate_token(NAVIDROME_PASSWORD, salt)

    cover_art_params = {
        "u": NAVIDROME_USER,
        "t": token,
        "s": salt,
        "v": "1.16.1",
        "c": "MastodonMusicBot/v3",
        "id": cover_art_id
    }

    try:
        image_response = requests.get(cover_art_url, params=cover_art_params, timeout=10)
        image_response.raise_for_status()
        return image_response.content
    except requests.exceptions.RequestException as e:
        print(f"Could not download album art: {e}")
        return None


def post_song_to_mastodon(song):
    """Posts a formatted message about a favorited song to Mastodon."""
    print(f"Preparing to post song '{song['title']}' by '{song['artist']}' to Mastodon.")

    # Download album cover art
    image_data = None
    if 'coverArt' in song:
        image_data = download_cover_art(song['coverArt'])

    if not image_data:
        print("No album art available, skipping this post.")
        return False

    # Upload image to Mastodon
    headers = {"Authorization": f"Bearer {MASTODON_ACCESS_TOKEN}"}
    files = {'file': ('album_cover.jpg', image_data, 'image/jpeg')}

    media_id = None
    try:
        response = requests.post(f"{MASTODON_API_BASE_URL}/api/v2/media", headers=headers, files=files)
        response.raise_for_status()
        media_id = response.json().get('id')
        print(f"Successfully uploaded album art. Media ID: {media_id}")
    except requests.exceptions.RequestException as e:
        print(f"Error uploading media to Mastodon: {e}")
        return False

    if not media_id:
        return False

    # Format genres as hashtags (first 3 genres)
    genres_text = ""
    if 'genre' in song and song['genre']:
        # Handle both string and list formats
        if isinstance(song['genre'], str):
            genre_list = song['genre'].split('/')
        else:
            genre_list = song['genre'] if isinstance(song['genre'], list) else [song['genre']]

        genres = [f"#{g.strip().replace(' ', '').replace('-', '')}" for g in genre_list if g.strip()][:3]
        genres_text = " ".join(genres)

    # Construct the status text
    status_text = (
        f"#NowPlaying\n\n"
        f"{song['artist']} - {song['title']}\n\n"
        f"{genres_text}"
    ).strip()

    payload = {
        "status": status_text,
        "media_ids[]": [media_id]
    }

    # Wait a moment before posting
    time.sleep(2)

    try:
        response = requests.post(f"{MASTODON_API_BASE_URL}/api/v1/statuses", headers=headers, data=payload)
        response.raise_for_status()
        print("Successfully posted song to Mastodon!")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error posting status to Mastodon: {e}")
        if e.response:
            print(f"Mastodon server response: {e.response.status_code} - {e.response.text}")
        return False


def main():
    """The main loop of the bot."""
    global posted_song_ids

    print("Starting Mastodon Music Bot - Favorites Monitor...")
    print("This bot will post to Mastodon whenever you favorite a song in Navidrome.")

    # Load previously posted songs
    load_posted_songs()

    while True:
        print("\n--- Checking for new favorited songs ---")

        starred_songs = get_starred_songs()

        # Find new favorites that haven't been posted yet
        new_favorites = [song for song in starred_songs if song['id'] not in posted_song_ids]

        if new_favorites:
            print(f"Found {len(new_favorites)} new favorited song(s) to post!")

            for song in new_favorites:
                print(f"\nNew favorite detected: {song['artist']} - {song['title']}")

                if post_song_to_mastodon(song):
                    # Mark as posted
                    posted_song_ids.add(song['id'])
                    save_posted_songs()
                    print(f"Successfully posted and saved song ID: {song['id']}")
                else:
                    print(f"Failed to post song ID: {song['id']}, will retry next cycle.")

                # Wait between posts to avoid rate limiting
                if len(new_favorites) > 1:
                    time.sleep(5)
        else:
            print("No new favorited songs found.")

        print(f"\nSleeping for {CHECK_INTERVAL_SECONDS} seconds...")
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBot stopped manually.")
        sys.exit(0)
    except Exception as e:
        print(f"A FATAL error occurred in the main loop: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        time.sleep(60)
        sys.exit(1)
