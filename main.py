import requests
import time
import hashlib
import random
import string
import sys
import os

# --- SCRIPT SETUP ---
# This is a special block to catch any error and print it, so the bot can't crash silently.
try:
    print("Mastodon Music Bot: Loading secrets...")
    # We will check each secret individually for better error messages
    from secrets import MASTODON_API_BASE_URL, MASTODON_ACCESS_TOKEN
    from secrets import NAVIDROME_BASE_URL, NAVIDROME_USER, NAVIDROME_PASSWORD
    from secrets import CHECK_INTERVAL_SECONDS, PROFILE_FIELD_NAME, ALBUM_POST_THRESHOLD
    print("Mastodon Music Bot: Secrets loaded successfully.")
except ImportError:
    print("CRITICAL ERROR: secrets.py file not found. Please ensure it exists.", file=sys.stderr)
    time.sleep(60)
    sys.exit(1)
except Exception as e:
    print(f"CRITICAL ERROR: Could not import from secrets.py. Check for syntax errors. Error: {e}", file=sys.stderr)
    time.sleep(60)
    sys.exit(1)


# --- GLOBAL STATE ---
last_scrobbled_song_id = None
album_listen_tracker = {
    "album_id": None,
    "played_song_ids": set(),
    "total_songs": 0,
    "has_been_posted": False
}

# --- HELPER FUNCTIONS ---

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
        "c": "MastodonMusicBot/v2",
        "f": "json"
    }
    base_params.update(params)

    try:
        # We construct the URL carefully using os.path.join for reliability
        # This prevents issues with trailing slashes causing a 404 error.
        url = os.path.join(NAVIDROME_BASE_URL, "rest", endpoint)
        
        print(f"Navidrome Request: Contacting URL -> {url}")
        response = requests.get(url, params=base_params, timeout=10) # Added a timeout
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

def update_mastodon_profile(song_info):
    """Updates the Mastodon profile with the latest song."""
    print(f"Attempting to update Mastodon profile with: '{song_info}'")
    headers = {"Authorization": f"Bearer {MASTODON_ACCESS_TOKEN}"}
    
    payload = {
        'fields_attributes[0][name]': PROFILE_FIELD_NAME,
        'fields_attributes[0][value]': song_info,
    }

    try:
        response = requests.patch(f"{MASTODON_API_BASE_URL}/api/v1/accounts/update_credentials", headers=headers, data=payload)
        response.raise_for_status()
        print("Successfully updated Mastodon profile.")
    except requests.exceptions.RequestException as e:
        print(f"Error updating Mastodon profile: {e}")
        if e.response:
            print(f"Mastodon server response: {e.response.status_code} - {e.response.text}")


# This function remains the same as before
def post_album_to_mastodon(album):
    """Posts a formatted message about a listened album to Mastodon."""
    print(f"Preparing to post album '{album['name']}' to Mastodon.")
    
    cover_art_url = os.path.join(NAVIDROME_BASE_URL, "rest", "getCoverArt")
    cover_art_params = {"u": NAVIDROME_USER, "p": NAVIDROME_PASSWORD, "v": "1.16.1", "c": "MastodonMusicBot/v2", "id": album['coverArt']}

    try:
        image_response = requests.get(cover_art_url, params=cover_art_params)
        image_response.raise_for_status()
        image_data = image_response.content
    except requests.exceptions.RequestException as e:
        print(f"Could not download album art: {e}")
        return

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
        return

    if not media_id:
        return

    rating_stars = ""
    rating = album.get('userRating', 0)
    if rating > 0:
        rating_stars = "★" * rating + "☆" * (5 - rating)

    genres = " ".join([f"#{g.replace(' ', '')}" for g in album.get('genre', '').split('/')][:3])

    status_text = (
        f"#NowPlaying\n"
        f"{album['artist']}\n"
        f"[{album['year']}] {album['name']}\n"
        f"{rating_stars}\n"
        f"{genres}"
    ).strip()
    
    payload = {
        "status": status_text,
        "media_ids[]": [media_id]
    }
    
    time.sleep(5)
    
    try:
        response = requests.post(f"{MASTODON_API_BASE_URL}/api/v1/statuses", headers=headers, data=payload)
        response.raise_for_status()
        print("Successfully posted album to Mastodon!")
    except requests.exceptions.RequestException as e:
        print(f"Error posting status to Mastodon: {e}")
        if e.response:
            print(f"Mastodon server response: {e.response.status_code} - {e.response.text}")


def main():
    """The main loop of the bot."""
    global last_scrobbled_song_id, album_listen_tracker
    print("Starting Mastodon Music Bot main loop...")

    while True:
        print("\n--- Checking for new activity ---")
        
        scrobbles_data = make_navidrome_request("getScrobbles", {"count": "10"})
        
        if scrobbles_data and "scrobbles" in scrobbles_data and "song" in scrobbles_data["scrobbles"]:
            # Check if the song list is not empty
            if not scrobbles_data["scrobbles"]["song"]:
                print("Scrobble list is empty. No new songs to report.")
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            latest_song = scrobbles_data["scrobbles"]["song"][0]
            
            if latest_song['id'] != last_scrobbled_song_id:
                print(f"New song detected: {latest_song['artist']} - {latest_song['title']}")
                song_info_for_profile = f"{latest_song['artist']} - {latest_song['title']}"
                update_mastodon_profile(song_info_for_profile)
                last_scrobbled_song_id = latest_song['id']
            else:
                print("No new song detected for profile update.")

            # Album tracking logic remains the same
            current_album_id = latest_song['albumId']
            if current_album_id != album_listen_tracker["album_id"]:
                album_details_data = make_navidrome_request("getAlbum", {"id": current_album_id})
                if album_details_data and "album" in album_details_data:
                    album_listen_tracker = {
                        "album_id": current_album_id,
                        "album_details": album_details_data["album"],
                        "played_song_ids": {latest_song['id']},
                        "total_songs": album_details_data["album"]["songCount"],
                        "has_been_posted": False
                    }
            else:
                album_listen_tracker["played_song_ids"].add(latest_song['id'])
            
            if album_listen_tracker["album_id"] is not None and not album_listen_tracker["has_been_posted"]:
                songs_played_count = len(album_listen_tracker['played_song_ids'])
                total_songs_count = album_listen_tracker['total_songs']
                if total_songs_count > 0 and (songs_played_count / total_songs_count) >= ALBUM_POST_THRESHOLD:
                    post_album_to_mastodon(album_listen_tracker["album_details"])
                    album_listen_tracker["has_been_posted"] = True
        else:
            print("Could not get scrobbles from Navidrome or scrobble list was empty. Will try again.")

        print(f"Sleeping for {CHECK_INTERVAL_SECONDS} seconds...")
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBot stopped manually.")
        sys.exit(0)
    except Exception as e:
        print(f"A FATAL error occurred in the main loop: {e}", file=sys.stderr)
        time.sleep(60)
        sys.exit(1)

