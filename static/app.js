const form = document.getElementById("commandForm");
const input = document.getElementById("commandInput");
const chat = document.getElementById("chatStream");
const statusText = document.getElementById("statusText");
const voiceToggle = document.getElementById("voiceToggle");
const settingsForm = document.getElementById("settingsForm");
const modelInput = document.getElementById("modelInput");
const maxTokensInput = document.getElementById("maxTokensInput");
const siteUrlInput = document.getElementById("siteUrlInput");
const siteNameInput = document.getElementById("siteNameInput");
const settingsStatus = document.getElementById("settingsStatus");
const micButton = document.getElementById("micButton");

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let speechRecognition = null;
let isListening = false;

function addBubble(text, role) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  bubble.textContent = text;
  chat.appendChild(bubble);
  chat.scrollTop = chat.scrollHeight;
}

function setBusy(isBusy) {
  statusText.textContent = isBusy ? "Processing command..." : "Ready for your command";
}

async function sendCommand(command) {
  if (!command.trim()) {
    return;
  }

  addBubble(command, "user");
  setBusy(true);

  try {
    const response = await fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        command,
        voice_output: voiceToggle.checked,
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      addBubble(data.error || "Request failed.", "assistant");
      return;
    }

    (data.messages || ["No response generated."]).forEach((message) => {
      addBubble(message, "assistant");
    });
  } catch (error) {
    addBubble("Could not reach server. Make sure the UI backend is running.", "assistant");
  } finally {
    setBusy(false);
  }
}

async function loadSettings() {
  try {
    const response = await fetch("/api/settings");
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Could not load settings");
    }

    const settings = data.settings || {};
    modelInput.value = settings.model || "openai/gpt-5.2";
    maxTokensInput.value = settings.max_tokens || 512;
    siteUrlInput.value = settings.site_url || "";
    siteNameInput.value = settings.site_name || "";
  } catch (error) {
    settingsStatus.textContent = "Could not load settings.";
  }
}

async function saveSettings(event) {
  event.preventDefault();
  settingsStatus.textContent = "Saving settings...";

  try {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: modelInput.value.trim(),
        max_tokens: Number(maxTokensInput.value || 512),
        site_url: siteUrlInput.value.trim(),
        site_name: siteNameInput.value.trim(),
      }),
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Could not save settings.");
    }

    settingsStatus.textContent = "Settings saved.";
  } catch (error) {
    settingsStatus.textContent = error.message || "Could not save settings.";
  }
}

function setupMicrophone() {
  if (!SpeechRecognition) {
    micButton.textContent = "Mic (Server)";
    micButton.title = "Browser speech recognition is unavailable. Using server microphone.";
    micButton.addEventListener("click", async () => {
      setBusy(true);
      micButton.classList.add("listening");
      try {
        const response = await fetch("/api/listen", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ voice_output: voiceToggle.checked }),
        });
        const data = await response.json();
        if (!response.ok) {
          addBubble(data.error || "Server microphone failed.", "assistant");
          return;
        }

        if (data.transcript) {
          addBubble(data.transcript, "user");
        }
        (data.messages || ["No response generated."]).forEach((message) => {
          addBubble(message, "assistant");
        });
      } catch (error) {
        addBubble("Could not reach server microphone endpoint.", "assistant");
      } finally {
        micButton.classList.remove("listening");
        setBusy(false);
      }
    });
    return;
  }

  speechRecognition = new SpeechRecognition();
  speechRecognition.lang = "en-IN";
  speechRecognition.interimResults = false;
  speechRecognition.maxAlternatives = 1;

  speechRecognition.onstart = () => {
    isListening = true;
    micButton.classList.add("listening");
    micButton.textContent = "Listening";
    statusText.textContent = "Listening for speech...";
  };

  speechRecognition.onend = () => {
    isListening = false;
    micButton.classList.remove("listening");
    micButton.textContent = "Mic";
    statusText.textContent = "Ready for your command";
  };

  speechRecognition.onerror = () => {
    addBubble("Microphone could not capture speech. Please try again.", "assistant");
  };

  speechRecognition.onresult = async (event) => {
    const transcript = event.results[0][0].transcript;
    input.value = transcript;
    await sendCommand(transcript);
  };

  micButton.addEventListener("click", () => {
    if (!speechRecognition) {
      return;
    }

    if (isListening) {
      speechRecognition.stop();
      return;
    }
    speechRecognition.start();
  });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const command = input.value;
  input.value = "";
  await sendCommand(command);
  input.focus();
});

document.querySelectorAll(".quick").forEach((button) => {
  button.addEventListener("click", async () => {
    await sendCommand(button.dataset.cmd || "");
  });
});

settingsForm.addEventListener("submit", saveSettings);

loadSettings();
setupMicrophone();
addBubble("Cortana UI is ready. Try typing: help", "assistant");
