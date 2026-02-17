# Downly 🚀

Downly is a modern, minimal **media downloader web app** designed for **personal and local use**.

It provides a clean, app-like interface to download videos and audio from supported platforms with ease.

---

## ✨ Features

- Premium dark UI with glassmorphism style
- Download **YouTube videos & Shorts**
- Download **Instagram Reels**
- Extract **MP3 audio**
- Fast and lightweight
- Mobile-friendly responsive design
- No ads, no tracking

---

## 🖥️ Intended Usage

This project is **meant to be run locally** on your own computer.

> ❗ Public cloud hosting (Render, Railway, etc.) is **not recommended**  
> Platforms like YouTube may block server-side downloads.

---

## ⚙️ Local Setup

### Requirements

- Python **3.10 or higher**
- `pip`
- `ffmpeg` (required for MP3 audio)

Make sure **ffmpeg is installed and added to PATH**.

---

### Install Dependencies

```bash
pip install flask yt-dlp
```

---

### Run the App

```bash
python app.py
```

Open your browser and visit:

```
http://127.0.0.1:5000
```

---

## 🎨 UI Design

- Dark-mode first
- Neon blue & cyan gradient accents
- Rounded components everywhere
- Smooth hover and press animations
- Centered card layout
- App-like experience (desktop & mobile)

---

## 📂 Project Structure

```text
Downly/
│── app.py
│
├── templates/
│   └── index.html
│
├── static/
│   └── logo.png
│
└── downloads/
```

---

## ⚠️ Important Notes

- This app is for **personal use only**
- Do not host publicly as a downloader service
- Downloading content may be subject to platform terms
- The author is not responsible for misuse

---

## 📜 Disclaimer

This project is created for **educational purposes** and **personal use only**.  
Users are responsible for complying with the terms of service of any platform they use.

---

## ❤️ Credits

Built using:
- **Flask** – backend framework
- **yt-dlp** – media downloading engine
- **ffmpeg** – audio/video processing

---

**Downly** — Download video & audio instantly
