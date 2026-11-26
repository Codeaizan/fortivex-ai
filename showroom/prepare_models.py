from .greetings import welcome_clip
from .services import Speech


def main():
    speech = Speech(allow_downloads=True)
    print("Preparing multilingual faster-whisper...", flush=True)
    _ = speech.recognizer
    for language in ("en", "hi", "auto"):
        print(f"Preparing Kokoro welcome audio ({language})...", flush=True)
        welcome_clip(speech, language)
    print("Speech assets are ready. Start llama.cpp separately for LFM3.", flush=True)


if __name__ == "__main__":
    main()
