"""ses.py — Windows yerleşik konuşma tanıma (System.Speech) ile yerel sesli giriş.

İsteğe bağlıdır ve varsayılan olarak kapalıdır (config/arayuz.toml -> sohbet.sesli_giris = false).
Yalnızca Windows'un yerleşik çevrimdışı SAPI motorunu kullanır; ses verisi dış ağa çıkmaz.
"""
from __future__ import annotations

import os
import subprocess
import threading
from typing import Any

from pevrai.ayarlar_arayuz import arayuz_oku
from pevrai.ceviri import dil, t

_KILIT = threading.Lock()

_PS_BETIK = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try {
    Add-Type -AssemblyName System.Speech -ErrorAction Stop
    $kulturen = New-Object System.Globalization.CultureInfo('__KULTUR__')
    try {
        $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine($kulturen)
    } catch {
        $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine
    }
    $rec.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
    $rec.SetInputToDefaultAudioDevice()
    $res = $rec.Recognize([TimeSpan]::FromSeconds(__SURE__))
    $rec.Dispose()
    if ($null -ne $res -and $res.Text) {
        Write-Output ("OK:" + $res.Text)
    } else {
        Write-Output "BOS:"
    }
} catch {
    Write-Output ("HATA:" + $_.Exception.Message)
}
"""


def etkin_mi() -> bool:
    """Sesli giriş ayarının açık olup olmadığını döndürür."""
    return bool(arayuz_oku().get("sohbet", {}).get("sesli_giris", False))


def dinle(sure_sn: int = 7) -> dict[str, Any]:
    """Varsayılan mikrofondan tek cümlelik konuşmayı metne çevirir."""
    if not etkin_mi():
        return {"ok": False, "hata": t("Sesli giriş kapalı. Ayarlar > Genel altından etkinleştirebilirsiniz.")}
    if os.name != "nt":
        return {"ok": False, "hata": t("Sesli giriş yalnızca Windows'ta desteklenir.")}
    if not _KILIT.acquire(blocking=False):
        return {"ok": False, "hata": t("Mikrofon zaten dinleniyor.")}
    try:
        sure = max(2, min(int(sure_sn or 7), 15))
        kultur = "tr-TR" if dil() == "tr" else "en-US"
        komut = _PS_BETIK.replace("__KULTUR__", kultur).replace("__SURE__", str(sure))
        bayraklar = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        sonuc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", komut],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=sure + 6,
            creationflags=bayraklar,
        )
        cikti = (sonuc.stdout or "").strip()
        for satir in reversed(cikti.splitlines()):
            satir = satir.strip()
            if satir.startswith("OK:"):
                metin = satir[3:].strip()
                return {"ok": True, "metin": metin}
            if satir.startswith("BOS:"):
                return {"ok": False, "hata": t("Konuşma algılanamadı.")}
            if satir.startswith("HATA:"):
                return {"ok": False, "hata": t("Windows konuşma tanıma başlatılamadı: {hata}", hata=satir[5:].strip())}
        return {"ok": False, "hata": t("Konuşma algılanamadı.")}
    except subprocess.TimeoutExpired:
        return {"ok": False, "hata": t("Sesli giriş zaman aşımına uğradı.")}
    except Exception as e:
        return {"ok": False, "hata": t("Windows konuşma tanıma başlatılamadı: {hata}", hata=e)}
    finally:
        _KILIT.release()
