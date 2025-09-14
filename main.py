import requests
import time
import hashlib
import random
import string
from secrets import (
    MASTODON_API_BASE_URL, MASTODON_ACCESS_TOKEN,
    NAVIDROME_BASE_URL, NAVIDROME_USER, NAVIDROME_PASSWORD,
    CHECK_INTERVAL_SECONDS, PROFILE_FIELD_NAME, ALBUM_POST_THRESHOLD
)

# --- GLOBAL STATE ---
# We use these variables to keep track of what the bot has already done.
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

    # These are standard parameters required by the Subsonic API
    base_params = {
        "u": NAVIDROME_USER,
        "t": token,
        "s": salt,
        "v": "1.16.1",  # Subsonic API version
        "c": "MastodonMusicBot", # Client name
        "f": "json" # We want responses in JSON format
    }
    # Add any extra parameters for the specific request
    base_params.update(params)

    try:
        url = f"{NAVIDROME_BASE_URL}/rest/{endpoint}"
        response = requests.get(url, params=base_params)
        response.raise_for_status() # This will raise an error for bad responses (like 404 or 500)
        data = response.json()
        if "subsonic-response" in data and data["subsonic-response"]["status"] == "ok":
            return data["subsonic-response"]
        else:
            error = data.get("subsonic-response", {}).get("error", {})
            print(f"Navidrome API Error: {error.get('message', 'Unknown error')}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to Navidrome: {e}")
        return None

def update_mastodon_profile(song_info):
    """Updates the Mastodon profile with the latest song."""
    print(f"Updating Mastodon profile with new song: {song_info}")
    headers = {"Authorization": f"Bearer {MASTODON_ACCESS_TOKEN}"}
    
    # This payload structure is required by the Mastodon API.
    # It updates the metadata fields. You can have up to 4.
    # Note: This will overwrite your existing fields, so you might need to add them here
    # if you want to keep them. For simplicity, we're only setting one.
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

def post_album_to_mastodon(album):
    """Posts a formatted message about a listened album to Mastodon."""
    print(f"Preparing to post album '{album['name']}' to Mastodon.")
    
    # 1. Get the album cover art
    cover_art_url = f"{NAVIDROME_BASE_URL}/rest/getCoverArt?u={NAVIDROME_USER}&p={NAVIDROME_PASSWORD}&v=1.16.1&c=MastodonMusicBot&id={album['coverArt']}"
    try:
        image_response = requests.get(cover_art_url)
        image_response.raise_for_status()
        image_data = image_response.content
    except requests.exceptions.RequestException as e:
        print(f"Could not download album art: {e}")
        return

    # 2. Upload the cover art to Mastodon
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

    # 3. Build the status text
    rating_stars = ""
    if 'starred' in album: # Check if rating info exists
        # Navidrome's API doesn't have star ratings, but some clients might add it.
        # This is a placeholder for if you find a way to set it.
        # We will simulate a rating for the example.
        rating = album.get('userRating', 0) # Assuming a 1-5 scale.
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
    
    # 4. Post the status with the attached image
    payload = {
        "status": status_text,
        "media_ids[]": [media_id]
    }
    
    # Wait a moment for media processing
    time.sleep(5)
    
    try:
        response = requests.post(f"{MASTODON_API_BASE_URL}/api/v1/statuses", headers=headers, data=payload)
        response.raise_for_status()
        print("Successfully posted album to Mastodon!")
    except requests.exceptions.RequestException as e:
        print(f"Error posting status to Mastodon: {e}")
        print(f"Response: {e.response.text}")

# --- MAIN LOGIC ---

def main():
    """The main loop of the bot."""
    global last_scrobbled_song_id, album_listen_tracker
    print("Starting Mastodon Music Bot...")

    while True:
        print("\n--- Checking for new activity ---")
        
        # Get the 10 most recently played songs
        scrobbles_data = make_navidrome_request("getScrobbles", {"count": "10"})
        
        if scrobbles_data and "scrobbles" in scrobbles_data and "song" in scrobbles_data["scrobbles"]:
            latest_song = scrobbles_data["scrobbles"]["song"][0]
            
            # --- 1. PROFILE UPDATE LOGIC ---
            if latest_song['id'] != last_scrobbled_song_id:
                print(f"New song detected: {latest_song['artist']} - {latest_song['title']}")
                song_info_for_profile = f"{latest_song['artist']} - {latest_song['title']}"
                update_mastodon_profile(song_info_for_profile)
                last_scrobbled_song_id = latest_song['id']
            else:
                print("No new song detected for profile update.")

            # --- 2. ALBUM POSTING LOGIC ---
            current_album_id = latest_song['albumId']

            # If we start listening to a new album...
            if current_album_id != album_listen_tracker["album_id"]:
                print(f"New album detected. Starting to track '{latest_song['album']}'.")
                # Reset the tracker for the new album
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
                     # Reset if we can't get details
                    album_listen_tracker["album_id"] = None

            # If it's the same album, add the song to our set of played songs
            else:
                album_listen_tracker["played_song_ids"].add(latest_song['id'])
                print(f"Continuing album '{latest_song['album']}'. "
                      f"Played {len(album_listen_tracker['played_song_ids'])} out of {album_listen_tracker['total_songs']} tracks.")

            # Check if we've reached the threshold and haven't posted yet
            if album_listen_tracker["album_id"] is not None and not album_listen_tracker["has_been_posted"]:
                songs_played_count = len(album_listen_tracker['played_song_ids'])
                total_songs_count = album_listen_tracker['total_songs']
                
                if total_songs_count > 0: # Avoid division by zero
                    listen_percentage = songs_played_count / total_songs_count
                    if listen_percentage >= ALBUM_POST_THRESHOLD:
                        print(f"Listen threshold of {ALBUM_POST_THRESHOLD * 100}% reached for album ID {album_listen_tracker['album_id']}.")
                        post_album_to_mastodon(album_listen_tracker["album_details"])
                        album_listen_tracker["has_been_posted"] = True # Mark as posted to avoid duplicates
        else:
            print("Could not get scrobbles from Navidrome. Will try again.")

        # Wait before checking again
        print(f"Sleeping for {CHECK_INTERVAL_SECONDS} seconds...")
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
