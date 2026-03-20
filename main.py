import speech_recognition as sr
import webbrowser
import pyttsx3
import musicLibrary
import requests
import os
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus


recognizer = sr.Recognizer()
engine = None
voice_output_enabled = True
newsapi = "95e0c610677047cd9e4439b9695c5f98"
notes_file = Path("notes.txt")
chat_history_file = Path("chat_history.json")
todo_file = Path("todos.json")
env_file = Path(".env")


def init_tts_engine():
    global engine
    engine = pyttsx3.init()
    engine.setProperty("volume", 1.0)
    engine.setProperty("rate", 170)

    voices = engine.getProperty("voices")
    if not voices:
        return

    # Prefer Hindi/Indian voice if present, otherwise use English fallback.
    preferred_index = 0
    for index, voice in enumerate(voices):
        voice_details = f"{voice.id} {voice.name}".lower()
        if "hi-" in voice_details or "hindi" in voice_details or "india" in voice_details:
            preferred_index = index
            break
    else:
        for index, voice in enumerate(voices):
            voice_details = f"{voice.id} {voice.name}".lower()
            if "zira" in voice_details:
                preferred_index = index
                break

    engine.setProperty("voice", voices[preferred_index].id)
    print(f"TTS voice selected: {voices[preferred_index].name}")


def normalize_command(text):
    command = text.lower().strip()
    replacements = {
        "khol": "open",
        "chalao": "play",
        "sunao": "play",
        "dhoondo": "search",
        "samachar": "news",
        "khabar": "news",
        "kaam": "task",
        "mausam": "weather",
    }
    for source, target in replacements.items():
        command = command.replace(source, target)
    return command


def speak(text):
    global engine
    if engine is None:
        init_tts_engine()

    try:
        engine.say(text)
        engine.runAndWait()
    except Exception:
        # Recover from intermittent driver errors by reinitializing once.
        init_tts_engine()
        engine.say(text)
        engine.runAndWait()


def respond(text):
    print(f"Assistant: {text}")
    save_chat_turn("assistant", text)
    if voice_output_enabled:
        try:
            speak(text)
        except Exception as e:
            print(f"TTS error: {e}")


def set_voice_output(enabled):
    global voice_output_enabled
    voice_output_enabled = bool(enabled)


def transcribe_audio(audio):
    # Try English first, then Hindi fallback for Hinglish commands.
    for language in ("en-IN", "hi-IN"):
        try:
            return recognizer.recognize_google(audio, language=language)
        except sr.UnknownValueError:
            continue
    raise sr.UnknownValueError()


def listen_once(timeout=6, phrase_time_limit=7):
    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.3)
        audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
    return transcribe_audio(audio)


def read_json_list(path):
    if not path.exists():
        return []

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def write_json_list(path, data):
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def save_chat_turn(role, text):
    history = read_json_list(chat_history_file)
    history.append(
        {
            "time": datetime.now().isoformat(timespec="seconds"),
            "role": role,
            "text": text,
        }
    )
    history = history[-20:]
    write_json_list(chat_history_file, history)


def get_api_key():
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if openrouter_api_key:
        return ("openrouter", openrouter_api_key)

    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_api_key:
        return ("openai", openai_api_key)

    if env_file.exists():
        try:
            with env_file.open("r", encoding="utf-8") as file:
                for raw_line in file:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    env_key = key.strip()
                    if env_key not in {"OPENAI_API_KEY", "OPENROUTER_API_KEY"}:
                        continue

                    if env_key == "OPENROUTER_API_KEY":
                        parsed = value.strip().strip('"').strip("'")
                        if parsed:
                            os.environ["OPENROUTER_API_KEY"] = parsed
                            return ("openrouter", parsed)

                    if env_key == "OPENAI_API_KEY":
                        parsed = value.strip().strip('"').strip("'")
                        if parsed:
                            os.environ["OPENAI_API_KEY"] = parsed
                            return ("openai", parsed)
        except OSError:
            pass

    return ("", "")


def get_ai_reply(user_text):
    provider, api_key = get_api_key()
    if not api_key:
        return "AI mode is not configured yet. Set OPENROUTER_API_KEY or OPENAI_API_KEY, or add one to .env file."

    try:
        from openai import OpenAI

        history = read_json_list(chat_history_file)
        recent = history[-6:]
        context_lines = [
            f"{item.get('role', 'user')}: {item.get('text', '')}"
            for item in recent
            if item.get("text")
        ]
        context_text = "\n".join(context_lines)

        system_prompt = (
            "You are Cortana, a concise and friendly voice assistant. "
            "Reply in 1-3 short sentences."
        )
        user_prompt = f"Recent conversation:\n{context_text}\n\nUser: {user_text}"

        if provider == "openrouter":
            base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
            model_name = os.getenv("OPENROUTER_MODEL", "openai/gpt-5.2")
            max_tokens = int(os.getenv("OPENROUTER_MAX_TOKENS", "512"))
            site_url = os.getenv("OPENROUTER_SITE_URL", "")
            site_name = os.getenv("OPENROUTER_SITE_NAME", "")

            extra_headers = {}
            if site_url:
                extra_headers["HTTP-Referer"] = site_url
            if site_name:
                extra_headers["X-OpenRouter-Title"] = site_name

            client = OpenAI(api_key=api_key, base_url=base_url)
            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                extra_headers=extra_headers or None,
            )
            text = completion.choices[0].message.content if completion.choices else ""
            return (text or "I could not generate a reply right now.").strip()

        model_name = os.getenv("OPENAI_MODEL", "gpt-5-mini")
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model_name,
            input=(
                f"{system_prompt}\n\n"
                f"{user_prompt}"
            ),
        )
        return (response.output_text or "I could not generate a reply right now.").strip()
    except Exception as e:
        error_text = str(e).lower()

        if "insufficient_quota" in error_text or "exceeded your current quota" in error_text:
            return "Your AI quota is finished. Please add billing or increase quota in your OpenAI account."
        if "requires more credits" in error_text or "error code: 402" in error_text or "can only afford" in error_text:
            return "OpenRouter credits are low for this request. Add credits or lower OPENROUTER_MAX_TOKENS in your environment."
        if "invalid_api_key" in error_text or "incorrect api key" in error_text or "authentication" in error_text:
            return "Your OpenAI API key looks invalid. Please update OPENAI_API_KEY and try again."
        if "rate limit" in error_text or "too many requests" in error_text:
            return "Too many AI requests right now. Please wait a few seconds and try again."
        if "timed out" in error_text or "connection" in error_text or "network" in error_text:
            return "I could not reach the AI service. Please check your internet and try again."

        return "AI service is temporarily unavailable. Please try again in a moment."


def add_task(task_text):
    tasks = read_json_list(todo_file)
    tasks.append(
        {
            "text": task_text,
            "done": False,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    write_json_list(todo_file, tasks)
    return len(tasks)


def list_tasks():
    tasks = read_json_list(todo_file)
    if not tasks:
        return []

    lines = []
    for index, task in enumerate(tasks, start=1):
        status = "done" if task.get("done") else "pending"
        lines.append(f"{index}. {task.get('text', '')} ({status})")
    return lines


def complete_task(task_number):
    tasks = read_json_list(todo_file)
    if task_number < 1 or task_number > len(tasks):
        return False

    tasks[task_number - 1]["done"] = True
    write_json_list(todo_file, tasks)
    return True


def parse_task_number(command_text):
    digits = "".join(ch for ch in command_text if ch.isdigit())
    if not digits:
        return None
    return int(digits)


def save_note(note_text):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with notes_file.open("a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {note_text}\n")


def processCommand(c):
    command_text = normalize_command(c)
    print(f"Command heard: {c}")
    save_chat_turn("user", c)

    if "open google" in command_text or "go to google" in command_text:
        webbrowser.open("http://www.google.com")
        respond("Opening Google")
    elif "open youtube" in command_text or "go to youtube" in command_text:
        webbrowser.open("http://www.youtube.com")
        respond("Opening Youtube")
    elif "open facebook" in command_text:
        webbrowser.open("http://www.facebook.com")
        respond("Opening Facebook")
    elif "open linkedin" in command_text:
        webbrowser.open("http://www.linkedin.com")
        respond("Opening Linkedin")
    elif "open instagram" in command_text:
        webbrowser.open("http://www.instagram.com")
        respond("Opening Instagram")
    
    elif command_text.startswith("play"):
        song = command_text.replace("play", "", 1).strip()
        if not song:
            respond("Please tell me the song name")
            return

        link = musicLibrary.music.get(song)
        if not link:
            # Try partial matching when recognition adds extra words.
            for title, song_link in musicLibrary.music.items():
                if title in song or song in title:
                    link = song_link
                    song = title
                    break

        if not link:
            respond(f"I could not find {song} in your music library")
            return

        webbrowser.open(link)
        respond("Playing " + song)

    elif "time" in command_text or "samay" in command_text:
        current_time = datetime.now().strftime("%I:%M %p")
        respond(f"Current time is {current_time}")

    elif "date" in command_text or "aaj" in command_text:
        today = datetime.now().strftime("%d %B %Y")
        respond(f"Today is {today}")

    elif command_text.startswith("note ") or command_text.startswith("remember "):
        note_text = command_text.replace("note", "", 1).replace("remember", "", 1).strip()
        if not note_text:
            respond("Please tell me what to save")
            return
        save_note(note_text)
        respond("Note saved")

    elif "show notes" in command_text or "read notes" in command_text:
        if not notes_file.exists():
            respond("You do not have any notes yet")
            return
        with notes_file.open("r", encoding="utf-8") as file:
            lines = [line.strip() for line in file.readlines() if line.strip()]
        if not lines:
            respond("You do not have any notes yet")
            return
        respond("Here are your latest notes")
        for line in lines[-3:]:
            respond(line)

    elif command_text.startswith("add task ") or command_text.startswith("todo "):
        task_text = command_text.replace("add task", "", 1).replace("todo", "", 1).strip()
        if not task_text:
            respond("Please tell me the task text")
        else:
            task_count = add_task(task_text)
            respond(f"Task added. You now have {task_count} tasks")

    elif "list tasks" in command_text or "show tasks" in command_text:
        task_lines = list_tasks()
        if not task_lines:
            respond("You do not have any tasks yet")
        else:
            respond("Here are your tasks")
            for line in task_lines[-5:]:
                respond(line)

    elif command_text.startswith("done task") or command_text.startswith("complete task"):
        task_number = parse_task_number(command_text)
        if task_number is None:
            respond("Please tell me the task number")
        elif complete_task(task_number):
            respond(f"Task {task_number} marked as done")
        else:
            respond("Task number not found")
    
    elif command_text.startswith("search ") or command_text.startswith("search for "):
        query = command_text.replace("search for", "", 1).replace("search", "", 1).strip()
        if query:
            webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}")
            respond(f"Searching for {query}")
        else:
            respond("Please tell me what to search for")

    elif "news" in command_text:
        r = requests.get(f"https://newsapi.org/v2/top-headlines?country=in&apiKey={newsapi}")
        if r.status_code == 200:
            # Parse the JSON response
            data = r.json()
            
            # Extract the articles
            articles = data.get('articles', [])
            
            # Print the headlines
            for article in articles:
                respond(article['title'])
        else:
            respond("I could not fetch the news right now")

    elif command_text.startswith("weather in ") or command_text == "weather":
        city = command_text.replace("weather in", "", 1).strip() or "Delhi"
        try:
            weather_url = f"https://wttr.in/{quote_plus(city)}?format=j1"
            weather_data = requests.get(weather_url, timeout=10).json()
            current = weather_data.get("current_condition", [{}])[0]
            temp_c = current.get("temp_C", "N/A")
            desc = current.get("weatherDesc", [{}])[0].get("value", "Unknown")
            humidity = current.get("humidity", "N/A")
            respond(f"Weather in {city}: {desc}, {temp_c} degree celsius, humidity {humidity} percent")
        except Exception:
            respond("I could not fetch weather right now")

    elif command_text.startswith("open "):
        target = command_text.replace("open", "", 1).strip()
        if target:
            webbrowser.open(f"https://www.google.com/search?q={quote_plus(target)}")
            respond(f"Opening search results for {target}")
        else:
            respond("Please tell me what to open")

    elif "voice test" in command_text or "test voice" in command_text:
        respond("Voice is working. I can hear and speak.")

    elif "help" in command_text or "what can you do" in command_text or "kya kar sakte ho" in command_text:
        respond("You can say open google, play skyfall, search for python, news, weather in Mumbai, time, date, note buy milk, add task call mom, list tasks, done task 2, or voice test")

    elif "exit" in command_text or "stop" in command_text or "band" in command_text:
        respond("Okay, shutting down")
        raise SystemExit(0)

    else:
        ai_reply = get_ai_reply(c)
        respond(ai_reply)

def is_likely_command(text):
    command_text = normalize_command(text)
    return (
        command_text.startswith("open ")
        or command_text.startswith("play ")
        or command_text.startswith("search ")
        or command_text.startswith("search for ")
        or command_text.startswith("note ")
        or command_text.startswith("remember ")
        or command_text.startswith("todo ")
        or command_text.startswith("add task ")
        or command_text.startswith("done task")
        or command_text.startswith("complete task")
        or command_text.startswith("go to ")
        or command_text.startswith("weather in ")
        or command_text == "weather"
        or "news" in command_text
        or "time" in command_text
        or "date" in command_text
        or "help" in command_text
        or "list tasks" in command_text
        or "show tasks" in command_text
        or "stop" in command_text
        or "exit" in command_text
        or "samay" in command_text
        or "aaj" in command_text
        or "kya kar sakte ho" in command_text
        or "show notes" in command_text
        or "read notes" in command_text
        or "voice test" in command_text
        or "test voice" in command_text
    )
    



if __name__ == "__main__":
    init_tts_engine()
    respond("Initializing Cortana.....")

    try:
        # Validate microphone access once so we don't spam errors in the loop.
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
    except Exception as e:
        print(f"Microphone setup failed: {e}")
        print("Install PyAudio and ensure a microphone is available.")
        respond("Microphone is not available. Please install PyAudio and check your audio input device")
        raise SystemExit(1)

    while True:
        #Listen for the wake word "Cortana"
        # obtain audio from the microphone
        print("Recognizing...")
        

        # recognize speech using Google Speech Recognition
        try:
            with sr.Microphone() as source:
                print("Listening...")
                recognizer.adjust_for_ambient_noise(source, duration=0.3)
                audio = recognizer.listen(source, timeout=5, phrase_time_limit=5)
            word = transcribe_audio(audio)
            print(f"Speech heard: {word}")

            # If wake word is present, strip it and process inline if command exists.
            if "cortana" in word.lower():
                inline_command = word.lower().replace("cortana", "", 1).strip(" ,.!?\t")
                if inline_command:
                    processCommand(inline_command)
                    continue
                respond("Yes, tell me the command")
                continue

            # Always process recognized speech to avoid silent no-op behavior.
            processCommand(word)

        # except sr.UnknownValueError:
        #     print("Sphinx could not understand audio")
        except sr.WaitTimeoutError:
            continue
        except sr.UnknownValueError:
            respond("Could not understand speech, please repeat")
            continue
        except KeyboardInterrupt:
            print("Stopping Cortana...")
            break
        except SystemExit:
            break
        except Exception as e:
            print("Error; {0}".format(e))



