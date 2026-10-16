## Pevrai 0.1.2

- **Streaming responses:** Real-time token streaming across Gemini, OpenAI-compatible, and Anthropic providers with instant cancellation support.
- **Scalable chat loading:** Lazy-loaded chat archives via lightweight index cache, reducing startup memory and opening large histories on demand.
- **Task & prompt templates:** Manage reusable prompts via `/` menu, quick insertion from messages, and dedicated management UI.
- **Local semantic search:** Safe cosine similarity search backed by local Ollama instances (`127.0.0.1` / `localhost`) and SQLite caching; external endpoints are strictly blocked. Integrated with Smart Notes and workspace files.
- **Reader enhancements (Okuma Atölyesi):** Turkish stem-aware search (`tr_kokler`), multi-column PDF text selection isolation, and thumbnail sidebar panel.
- **Voice input:** Offline speech-to-text powered by Windows built-in SAPI (`System.Speech.Recognition`), disabled by default for privacy.
- **Scheduled & recurring tasks:** Daily, weekly, and one-shot recurring task scheduling governed by the exact same strict permission gate (`gate.py`) and quota limits (`journal.kota_ayir`).
- **Architecture & maintainability:** Splitted monolithic frontend (`app.js`, `stil.css`) and backend modules while preserving zero-build/zero-CDN and strict security boundaries.

**Türkçe:**
- **Gerçek akışlı yanıtlar:** Gemini, OpenAI-uyumlu ve Anthropic sağlayıcılarında gerçek zamanlı token akışı ve anında durdurma desteği.
- **Ölçeklenebilir sohbet yükleme:** Hafif indeks önbelleği ile tembel yükleme (lazy loading); açılış süresi ve bellek tüketimi düşürüldü.
- **İstem ve görev şablonları:** `/` menüsüyle hızlı çağrılabilen şablonlar, mesajlardan şablon kaydetme ve yönetim paneli.
- **Yerel anlamsal arama:** Yalnızca yerel Ollama (`127.0.0.1` / `localhost`) ile çalışan, SQLite önbellekli kosinüs benzerliği motoru; Smart Notes ve çalışma alanı dosyalarına bağlandı.
- **Okuma Atölyesi geliştirmeleri:** Türkçe kök bulmalı tam metin arama (`tr_kokler`), çok sütunlu sayfalarda sütun içi seçim yalıtımı ve küçük resimler sekmesi.
- **Sesli giriş:** Windows yerleşik çevrimdışı SAPI motoruyla yerel mikrofon girişi (varsayılan kapalı).
- **Zamanlanmış görevler:** Günlük, haftalık ve tek seferlik yerel görev zamanlayıcı; tüm onay kapısı ve kota kuralları korunur.
- **Modüler mimari:** `index.html` ve büyük Python modülleri bölündü, CDN/eval yasağı ve güvenlik sınırları korundu.

## Pevrai 0.1.1

- Limina is now Pevrai. Existing installation identity, settings and chats remain compatible.
- Optional daily update notification; downloads and installation stay manual.
- Edit agents from the office card; browser tests close only their own processes.
- The office keeps the seated pose on the final walking frame and avoids redundant rendering when team selection stays the same.
- Undo records and backup/trash filenames use unique IDs, even when the clock repeats. Existing journals remain readable.
- Bundled version metadata and isolated, time-limited package checks. Source tests must pass before a release is built.

**Türkçe:** Limina'nın yeni adı Pevrai. Eski kurulum kimliği, ayarlar ve sohbetlerle
uyumluluk korunur. İsteğe bağlı günlük güncelleme bildirimi, ofis kartından ajan
düzenleme ve test süreçlerinin temizlenmesi eklendi. Paket sürümü ve MCP yanıtı
yalıtılmış ortamda, süre sınırıyla doğrulanır; yayın öncesinde kaynak testleri çalışır.


## Download

**Pevrai-Setup.exe**: Windows 10/11, 64-bit. No Python needed, no admin rights needed.

1. Download `Pevrai-Setup-<version>.exe` from **Assets** below and run it.
2. Windows may show *"Windows protected your PC"*: the installer is not code-signed yet.
   Click **More info → Run anyway**. You can check the file against `SHA256SUMS.txt`.
3. On first start, a short setup screen asks for language, folders and tools. Then add a model
   connection (an API key, or a local Ollama server) in **Settings › Model**.

Requirements: [Google Chrome](https://www.google.com/chrome/) for the browser tools.
Optional: [LibreOffice](https://www.libreoffice.org/) for converting Word/PowerPoint to PDF.

Your data (settings, chats, journal) is stored in `%LOCALAPPDATA%\Pevrai` and `~\.vekil`, not
in the program folder. Uninstalling keeps it, so reinstalling brings your settings back.
If an existing `%LOCALAPPDATA%\Limina` data folder is present, Pevrai continues to use it.

---

**Türkçe:** `Pevrai-Setup-<sürüm>.exe` dosyasını aşağıdaki **Assets** bölümünden indirip çalıştır.
Python ya da yönetici izni gerekmez. Windows "Bilgisayarınız korundu" derse **Ek bilgi → Yine de
çalıştır**'a tıkla (kurulum programı henüz imzalı değil). İlk açılışta kurulum ekranı dil,
klasör ve araç seçimini sorar; ardından **Ayarlar › Model**'den bir model bağlantısı ekle.
