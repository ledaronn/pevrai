## Pevrai 0.1.3

- **Terminal access & live file diffs (`terminal_run`):** Supervised command execution inside configured workspace write roots (`kum/`) with a Claude Code-style black `.terminal-kart` UI showing the command, live waiting/running state, exit code, stdout/stderr output, and automatic `+` / `-` line-by-line file diffs (`dosya_farklari`). Read-only inspection commands (`git status`, `git diff`, `pytest -q`, `dir`, etc.) run automatically while write/install/destructive commands require explicit user confirmation and dangerous system/network-exec commands (`Format-Volume`, `Invoke-Expression`, `reg delete`, etc.) are hard-blocked.
- **Partial desktop window control (`window_list`, `window_read`, `window_click`, `window_type`, `window_key`):** Native Windows UI Automation (`UIAutomationCore.dll` / `user32.dll`) tools to inspect and interact with **already open** desktop applications. Closed programs are never launched automatically (the agent directs to approval-gated `open_item`), sensitive windows (Password Manager, KeePass, Bitwarden, Windows Security, Credential Manager, Registry Editor, Pevrai itself) are blocklisted, and critical buttons (`Delete`, `Format`, `Send`, `Publish`, `Pay`) or dangerous hotkeys (`Alt+F4`, `Ctrl+W`) always trigger extra confirmation.
- **UI & streaming polish:** Removed the orange focus border on the chat input box; fixed live token streaming transitions before tool calls and approval cards (`akisParcasiEkle`, `aktifAkis` cleanup).

**Türkçe:**
- **Terminal erişimi ve canlı değişiklik kartı (`terminal_run`):** Çalışma klasörü (`kum/`) içinde denetimli komut çalıştırma, Claude Code tarzı siyah `.terminal-kart` arayüzü (komut, onay/çalışma durumu, çıkış kodu, stdout/stderr ve değiştirilen dosyalarda otomatik `+`/`-` satır farkı önizlemesi). Salt-okuma komutları (`git status`, `git diff`, `pytest -q`, `dir` vb.) onaysız çalışır; yazma/paket kurma/silme komutları onay ister; tehlikeli sistem/uzaktan kod çalıştırma komutları (`Format-Volume`, `Invoke-Expression`, `reg delete` vb.) kesin olarak engellenir.
- **Kısmi masaüstü pencere kontrolü (`window_list`, `window_read`, `window_click`, `window_type`, `window_key`):** Windows UI Automation (`UIAutomationCore.dll` / `user32.dll`) ile **yalnızca açık olan** masaüstü pencerelerini okuma ve kontrol etme. Kapalı programlar asla kendi kendine açılmaz (onaylı `open_item` aracına yönlendirilir), parola yöneticileri ve güvenlik pencereleri kara listededir, kritik düğmeler (`Sil`, `Gönder`, `Yayınla`, `Öde`) ve tehlikeli kısayollar (`Alt+F4`, `Ctrl+W`) ek onay ister.
- **Arayüz ve akış iyileştirmeleri:** Sohbet yazma kutusundaki turuncu odak çerçevesi kaldırıldı; araç çağrısı ve onay kartı öncesinde canlı akış (`akisParcasiEkle`) geçişleri düzeltildi.

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
