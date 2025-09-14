Mastodon Music Bot
This is a simple bot that connects to a Navidrome music server and a Mastodon account to do two things:

Update Profile: Adds a "Now Playing" field to your Mastodon profile with the last song you listened to.

Post Albums: When you listen to 75% or more of an album in one session, it automatically creates a post on your Mastodon feed with the album art and details.

This project is designed to be run in a Docker container on a home server.

Setup
Copy the contents of secrets.example.py to a new file named secrets.py.

Fill in all the required values in secrets.py.

Build the Docker image: docker build -t mastodon-music-bot .

Run the Docker container: docker run -d --restart always --name mastodon-bot mastodon-music-bot