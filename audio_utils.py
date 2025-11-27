from pydub import AudioSegment
import os

def convert_to_mp3(input_path, output_path):
    song = AudioSegment.from_file(input_path)
    song.export(output_path, format="mp3")
    return output_path

def create_preview(input_path, output_path, duration_ms=30000):
    song = AudioSegment.from_file(input_path)
    preview = song[:duration_ms]
    preview.export(output_path, format="mp3")
    return output_path

def save_temp_file(file_name):
    temp_dir = "temp"
    os.makedirs(temp_dir, exist_ok=True)
    return os.path.join(temp_dir, file_name)
