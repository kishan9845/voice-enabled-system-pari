import os
import sys
import re
import time
import pyttsx3
import pyautogui
import speech_recognition as sr

from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout
from PyQt5.QtCore import QTimer, QThread, pyqtSignal, Qt

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
WAKE_WORDS = ["hi pari", "hey pari", "hi party", "hi parry", "hi perry"]  # tolerate misheard variants

# ---------------------------------------------------------------------------
# TTS Worker Thread (prevents GUI freeze while speaking)
# ---------------------------------------------------------------------------
class TTSWorker(QThread):
    finished = pyqtSignal()

    def __init__(self, text):
        super().__init__()
        self.text = text

    def run(self):
        try:
            engine = pyttsx3.init()
            voices = engine.getProperty('voices')
            for voice in voices:
                if "female" in voice.name.lower() or "zira" in voice.name.lower():
                    engine.setProperty('voice', voice.id)
                    break
            engine.setProperty('rate', 150)
            engine.setProperty('volume', 1.0)
            engine.say(self.text)
            engine.runAndWait()
            engine.stop()
        except Exception as e:
            print(f"TTS Error: {e}")
        finally:
            self.finished.emit()


# ---------------------------------------------------------------------------
# Speech Recognition Worker Thread (runs continuously, emits every phrase heard)
# ---------------------------------------------------------------------------
class SpeechWorker(QThread):
    heard = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        r = sr.Recognizer()
        r.dynamic_energy_threshold = True
        mic = sr.Microphone()

        with mic as source:
            r.adjust_for_ambient_noise(source, duration=0.5)

        while self._running:
            try:
                with mic as source:
                    audio = r.listen(source, timeout=5, phrase_time_limit=8)
                text = r.recognize_google(audio)
                self.heard.emit(text.lower())
            except sr.WaitTimeoutError:
                continue
            except sr.UnknownValueError:
                continue
            except sr.RequestError:
                time.sleep(2)  # network hiccup, back off briefly
                continue
            except Exception:
                continue


# ---------------------------------------------------------------------------
# Simple floating status window (no images)
# ---------------------------------------------------------------------------
class PariWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setFixedSize(240, 70)
        self.setStyleSheet("background-color: #1e1e2e; border-radius: 10px;")

        layout = QVBoxLayout(self)
        self.label = QLabel("Pari")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

        self.set_status("Say 'Hi Pari'", "#6c7086")
        self._old_pos = None

    def set_status(self, text, color="#cdd6f4"):
        self.label.setText(text)
        self.label.setStyleSheet(
            f"color: {color}; font-size: 14px; font-family: Segoe UI;"
        )

    # Draggable window (click and drag anywhere on it)
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._old_pos = event.globalPos()

    def mouseMoveEvent(self, event):
        if self._old_pos is not None:
            delta = event.globalPos() - self._old_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self._old_pos = event.globalPos()

    def mouseReleaseEvent(self, event):
        self._old_pos = None


# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------
app = QApplication(sys.argv)
window = PariWindow()

screen = QApplication.primaryScreen().availableGeometry()
window.move(screen.width() - window.width() - 30, screen.height() - window.height() - 60)
window.show()

state = {"mode": "wake", "send_on_stop": False}   # modes: wake, command, dictation
tts_active = False
speech_worker = None
active_tts_threads = []


def update_status_label():
    mode = state["mode"]
    if mode == "wake":
        window.set_status("Say 'hi Pari'", "#6c7086")
    elif mode == "command":
        window.set_status("Listening for command...", "#a6e3a1")
    elif mode == "dictation":
        window.set_status("Typing what you say...", "#cba6f7")


def speak(text, on_complete=None):
    global tts_active
    tts_active = True
    window.set_status("Speaking...", "#f9e2af")

    worker = TTSWorker(text)
    active_tts_threads.append(worker)

    def done():
        global tts_active
        tts_active = False
        if worker in active_tts_threads:
            active_tts_threads.remove(worker)
        update_status_label()
        if on_complete:
            on_complete()

    worker.finished.connect(done)
    worker.start()


# ---------------------------------------------------------------------------
# Dictation mode (types whatever you say into the currently focused window)
# ---------------------------------------------------------------------------
def enter_dictation_mode(send_on_stop=False):
    state["mode"] = "dictation"
    state["send_on_stop"] = send_on_stop
    update_status_label()


def exit_dictation_mode():
    state["mode"] = "wake"
    state["send_on_stop"] = False
    update_status_label()


# ---------------------------------------------------------------------------
# Gmail compose automation
# ---------------------------------------------------------------------------
def compose_gmail_message(name):
    window.set_status("Opening Gmail...", "#89b4fa")
    os.system("start chrome https://mail.google.com")

    def after_page_load():
        pyautogui.press('c')  # Gmail's compose shortcut (must be enabled in Gmail settings)

        def after_compose_open():
            pyautogui.write(name, interval=0.05)
            time.sleep(1)
            pyautogui.press('down')   # pick top contact suggestion
            pyautogui.press('tab')    # -> Subject
            pyautogui.write("Message from Pari", interval=0.03)
            pyautogui.press('tab')    # -> Body

            speak(
                f"Ready. Go ahead and dictate your message to {name}. "
                f"Say send message when you're done, or stop typing to cancel.",
                lambda: enter_dictation_mode(send_on_stop=True)
            )

        QTimer.singleShot(2500, after_compose_open)

    # Give Chrome/Gmail time to open and load before pressing shortcuts
    QTimer.singleShot(4000, after_page_load)


# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------
def execute(command):
    if not command:
        update_status_label()
        return

    if "open notepad" in command:
        os.system("notepad")
        speak("Opening Notepad")

    elif "open calculator" in command:
        os.system("calc")
        speak("Opening Calculator")

    elif "save file" in command:
        pyautogui.hotkey("ctrl", "s")
        speak("File saved")

    elif "shutdown" in command:
        speak("Shutting down your computer now.", lambda: os.system("shutdown /s /t 1"))

    elif "restart" in command:
        speak("Restarting your computer now.", lambda: os.system("shutdown /r /t 1"))

    elif "close window" in command:
        speak("Closing the current window")
        pyautogui.hotkey("alt", "f4")

    elif "open chrome" in command:
        os.system("start chrome")
        speak("Opening Google Chrome")
    elif "close chrome" in command:
        speak("Closing Google Chrome")
        os.system("taskkill /im chrome.exe /f")

    elif "close edge" in command:
        speak("Closing Microsoft Edge")
        os.system("taskkill /im msedge.exe /f")
    elif "open edge" in command:
        os.system("start msedge")
        speak("Opening Microsoft Edge")
 
    elif "open word" in command:
        os.system("start winword")
        speak("Opening Microsoft Word")

    elif "close word" in command:
        speak("Closing Microsoft Word")
        os.system("taskkill /im winword.exe /f")

    elif "open youtube" in command:
        os.system("start chrome https://www.youtube.com")
        speak("Opening YouTube")
    elif "close youtube" in command:
        speak("Closing YouTube")
        os.system("taskkill /im chrome.exe /f")  # Assuming YouTube is opened in Chrome
    elif "open gmail" in command:
        m = re.search(r"compose (?:a )?message to (\w+)", command)
        if m:
            compose_gmail_message(m.group(1).capitalize())
        else:
            os.system("start chrome https://mail.google.com")
            speak("Opening Gmail")

    elif "start typing" in command or "take dictation" in command:
        speak(
            "Okay, click into the text field you want. I'll type what you say. "
            "Say stop typing when done.",
            lambda: enter_dictation_mode(send_on_stop=False)
        )

    elif "exit" in command or "quit" in command:
        speak("thank you boss have a nice day", shutdown_app)

    else:
        speak("Sorry, I didn't understand.")

    update_status_label()


def shutdown_app():
    if speech_worker:
        speech_worker.stop()
    app.quit()


# ---------------------------------------------------------------------------
# Central handler for every phrase heard, routed by current mode
# ---------------------------------------------------------------------------
def on_heard(text):
    if tts_active or not text:
        return  # ignore stray audio picked up while Pari itself is speaking

    mode = state["mode"]

    if mode == "wake":
        if any(w in text for w in WAKE_WORDS):
            remainder = text
            for w in WAKE_WORDS:
                remainder = remainder.replace(w, "").strip()
            if remainder:
                execute(remainder)          # e.g. "hi pari open notepad" -> runs immediately
            else:
                state["mode"] = "command"
                update_status_label()
                speak("Yes boss?")
        return

    if mode == "command":
        state["mode"] = "wake"
        execute(text)
        return

    if mode == "dictation":
        if "stop typing" in text or "stop dictation" in text:
            exit_dictation_mode()
            speak("Stopped typing.")
            return
        if "send message" in text and state.get("send_on_stop"):
            pyautogui.hotkey('ctrl', 'enter')  # Gmail's send shortcut (must be enabled)
            exit_dictation_mode()
            speak("Message sent.")
            return
        pyautogui.write(text + " ", interval=0.02)
        return


def start_listening():
    global speech_worker
    speech_worker = SpeechWorker()
    speech_worker.heard.connect(on_heard)
    speech_worker.start()


app.aboutToQuit.connect(lambda: speech_worker.stop() if speech_worker else None)

QTimer.singleShot(500, lambda: speak("Pari is online boss, how can i help you today .", start_listening))

sys.exit(app.exec_())