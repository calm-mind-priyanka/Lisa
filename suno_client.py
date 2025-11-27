import requests
import os

SUNO_URL = "https://api.suno.ai/v1/generate"  # Replace with your Suno API endpoint

def generate_song(lyrics, style="pop", track_file_path=None):
    headers = {
        "Authorization": f"Bearer {os.getenv('SUNO_API_KEY')}",
    }

    data = {
        "lyrics": lyrics,
        "style": style
    }

    files = {}
    if track_file_path:
        files["track"] = open(track_file_path, "rb")

    response = requests.post(SUNO_URL, json=data, files=files)
    if response.status_code == 200:
        return response.content
    else:
        raise Exception(f"Suno API Error: {response.text}")
