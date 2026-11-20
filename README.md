# Pixie 🧚 — my own Jarvis

Pixie is a personal desktop AI assistant for Windows, inspired by Jarvis and Nixi.
**Hold Right Alt, say what you want, let go.** A small popup appears in the middle of your screen,
Pixie answers, and the work happens **in the background**. Nothing steals focus from what you're doing.
The AI runs **100% locally** through [Ollama](https://ollama.com), so it's free and private.

<p align="center"><img src="docs/popup.png" width="560" alt="Pixie popup: listening, thinking, reply, done, typing"></p>

> **Status:** 🚧 v0.2: popup UI, hold-to-talk voice, background tasks, apps, Spotify, web search, email drafts, modes.

---

## ✨ What Pixie can do

| Category | Example commands | Status |
|---|---|---|
| 🎵 **Spotify** | "Open Spotify and play my liked songs", "Play Eminem", "Skip", "Pause", "Volume 30" | ✅ |
| 🚀 **Apps & games** | "Open Discord", "Launch Valorant", "Close Chrome" | ✅ |
| 🔎 **Search** | "What's the weather in Sofia?", "Search best RTX 4070 laptops": you get a short summary, no browser tab | ✅ |
| ✉️ **Emails** | "Write an email to my professor asking for an extension": the draft is **copied to your clipboard** | ✅ |
| 🎮 **Modes** | "Activate game mode" opens Discord, plays your liked songs and launches your game | ✅ |
| 🎙️ **Voice** | Hold **Right Alt** and talk, with local Whisper speech-to-text | ✅ |
| ⌨️ **Typing** | **Double-tap Right Alt** to type a command instead | ✅ |
| 💬 **Text replies** | Pixie answers in the popup only. It never talks out loud | ✅ |
| 📁 **Files** | "Clean up my Downloads", "Find the PDF from yesterday" | 🔜 |

### The popup
| You do | Pixie shows |
|---|---|
| **Hold Right Alt** | 🔵 *Listening*: the orb and bars react to your voice |
| **Release** | 🟣 *Thinking*: what you said, while it decides |
| | 💜 *Reply*, e.g. "On it 👍", then the popup fades away |
| (task finishes) | 🟢 *Done*, e.g. "Playing your Liked Songs on shuffle 🎵" |
| **Double-tap Right Alt** | ⌨️ a text box. Enter sends, Esc closes |

- The popup **never steals focus** (except the text box), so it's safe to use mid-game.
- Pressing Right Alt together with another key (AltGr shortcuts like `AltGr+Q` → `@`) is ignored,
  so normal typing never triggers Pixie.
- Pixie lives in the **system tray**: right-click it to type a command or quit.

### Background-first
- Pixie replies instantly ("On it 👍") and runs the work as a **background task**, so you can keep
  typing new commands or keep gaming.
- When a task finishes you get a **Windows notification**.
- Spotify is controlled through the **Spotify Web API**, so Liked Songs start playing without the
  Spotify window ever coming to the front. If Spotify isn't running, Pixie starts it minimized.
- Apps and games are launched **minimized and unfocused**.

### Safety
Pixie **never sends emails**. It only writes drafts for you to paste and send yourself.
Anything destructive (like deleting files) will always ask for confirmation first.

---

## 🧠 How it works

```
 🎙️ hold Right Alt: "open spotify and play my liked songs"
        │  Whisper (local) → text
        ▼
 ┌────────────┐     ┌──────────────┐     ┌────────────────────┐
 │   Brain    │ ──► │ Task runner  │ ──► │       Tools        │
 │ local LLM  │     │ asyncio jobs │     │ play_liked_songs() │
 │ (Ollama)   │     │ in threads   │     │ open_app() ...     │
 │ picks tool │     └──────────────┘     └────────────────────┘
 └────────────┘            │
        │                  ▼
 popup: "On it 👍"   popup: "Playing your Liked Songs on shuffle 🎵"
```

1. **Brain** (`pixie/brain.py`) sends your message to the local LLM with a list of tools. The LLM
   answers with **tool calls**, e.g. `play_liked_songs(shuffle=true)`.
   Exact mode phrases like "activate game mode" skip the LLM, so they run instantly.
2. **Task runner** (`pixie/tasks.py`) runs every tool call as a background job.
3. **Tools** (`pixie/tools/`) are plain Python functions with a `@tool` decorator.
   **Adding a skill = adding a function.**

```python
from . import tool

@tool("lock_pc", "Lock the computer.")
def lock_pc() -> str:
    import ctypes
    ctypes.windll.user32.LockWorkStation()
    return "PC locked 🔒"
```

---

## 🚀 Getting started (Windows)

### 1. Install Ollama + a model
Download Ollama from [ollama.com](https://ollama.com), then:
```bash
ollama pull qwen2.5:7b
```
`qwen2.5:7b` is good at tool calling and runs well on a GPU with ~8 GB VRAM.
If you have more VRAM you can use `qwen2.5:14b`, and on weaker hardware `llama3.2:3b`.

### 2. Install Pixie
```bash
git clone https://github.com/yavmomdev/Pixie-Jarvis.git
cd Pixie-Jarvis
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy config.example.yaml config.yaml
```

### 3. Connect Spotify (optional, needs Spotify Premium)
1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) → **Create app**.
2. Set the Redirect URI to `http://127.0.0.1:8888/callback` and select **Web API**.
3. Put the **Client ID** and **Client Secret** into `config.yaml`.
4. The first time you play something, a browser opens once so you can log in.

### 4. Run
```bash
python -m pixie              # popup UI, hold Right Alt to talk
pythonw -m pixie             # same, without a console window
python -m pixie --console    # text-only mode in the terminal
```
The first start downloads the Whisper speech model (`small` ≈ 500 MB), and after that it's instant.
Then **hold Right Alt** and say *"open Spotify and play my liked songs"*.

> 💡 **GPU speech-to-text:** Whisper runs on your NVIDIA GPU if CUDA libraries are available
> (`pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`), otherwise it falls back to the CPU automatically.
> With a GPU, set `voice.stt_model: large-v3-turbo` for the best accuracy (also for Bulgarian).
>
> 🎮 **Games running as administrator** can block global hotkeys. If Right Alt doesn't work in a
> game, run Pixie as administrator too.

---

## ⚙️ Configuration

Everything lives in `config.yaml` (it's git-ignored, so your keys stay private):

- `ollama.model`: which local model to use
- `ui.hotkey`: the hold-to-talk key (default `alt_r`, Right Alt); `ui.position`: `center` / `top` / `bottom`
- `voice.stt_model` / `voice.language`: the Whisper model and language (`null` = auto-detect)
- `apps`: nicknames for apps that aren't found automatically (anything in the Start Menu is found
  automatically). Steam games work as `steam://rungameid/<id>`.
- `spotify`: API keys

### Modes
A mode is a YAML file in `modes/`, holding a list of tool calls:

```yaml
# modes/game_mode.yaml
name: game mode
triggers: ["activate game mode", "game mode on"]
delay: 2
steps:
  - open_app: {name: discord}
  - play_liked_songs: {shuffle: true}
  - open_app: {name: valorant}
```

> ℹ️ Discord has no official way to auto-join a voice call, so for now game mode just opens Discord.

---

## 📂 Project structure

```
Pixie-Jarvis/
├── pixie/
│   ├── __main__.py      # python -m pixie  (popup UI, or --console)
│   ├── hotkey.py        # hold Right Alt to talk, double-tap to type
│   ├── ui/
│   │   ├── app.py       # tray icon + wiring: voice → brain → tasks → popup
│   │   └── overlay.py   # the center popup (orb, mic bars, animations)
│   ├── voice/
│   │   ├── recorder.py  # microphone
│   │   └── stt.py       # local Whisper speech-to-text
│   ├── brain.py         # LLM → tool calls
│   ├── tasks.py         # background task runner
│   ├── llm.py           # Ollama client
│   ├── notify.py        # Windows notifications
│   ├── config.py
│   └── tools/           # one file per skill
│       ├── apps.py      # open / close apps & games
│       ├── spotify.py   # liked songs, play, pause, skip, volume
│       ├── search.py    # DuckDuckGo + LLM summary
│       ├── email.py     # email drafts → clipboard
│       └── modes.py     # run modes from modes/*.yaml
├── modes/
│   └── game_mode.yaml
├── config.example.yaml
└── requirements.txt
```

---

## 🗺️ Roadmap

- [x] **v0.1**: text commands → local LLM → tools (apps, Spotify, search, email drafts, modes), background tasks + notifications
- [x] **v0.2**: center popup UI, hold Right Alt to talk (local Whisper), double-tap to type, tray icon
- [ ] **v0.4**: file tools (find, organize, clean up Downloads)
- [ ] **v0.5**: more modes (study mode, focus mode) and auto-start with Windows
- [ ] Later: remembering preferences, multi-step tasks, plugins

---

## 📄 License

[MIT](LICENSE) © 2026 yavmomdev
