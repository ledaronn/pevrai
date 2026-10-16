"""pencere_yardimcilar.py — pywebview ve Windows arayüz yardımcıları.

Pencere döngüsü, pano okuma ve donma izleyicisi.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any

from pevrai import PROJE_KOKU, journal


def pano_dosyalari() -> list[str]:
    """Windows panosundaki dosya yollarini okur (Explorer'da 'Kopyala' ile
    konan CF_HDROP). Tarayici clipboard API'si bunu vermez.
    Windows disinda ya da panoda dosya yoksa bos liste."""
    if sys.platform != "win32":
        return []
    import ctypes

    user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
    CF_HDROP = 15
    yollar: list[str] = []
    try:
        if not user32.OpenClipboard(None):
            return []
        try:
            h_drop = user32.GetClipboardData(CF_HDROP)
            if h_drop:
                adet = shell32.DragQueryFileW(h_drop, 0xFFFFFFFF, None, 0)
                for i in range(adet):
                    uzunluk = shell32.DragQueryFileW(h_drop, i, None, 0)
                    arabellek = ctypes.create_unicode_buffer(uzunluk + 1)
                    shell32.DragQueryFileW(h_drop, i, arabellek, uzunluk + 1)
                    if arabellek.value:
                        yollar.append(arabellek.value)
        finally:
            user32.CloseClipboard()
    except Exception:
        return []
    return yollar


def takilma_bekcisi(pencere: Any) -> None:
    """Arayuz thread'i donarsa butun thread'lerin yigin izini
    ~/.vekil/takilma.log dosyasina yazar."""
    import faulthandler

    ESIK_SN = 15.0

    def _dongu() -> None:
        time.sleep(5.0)
        try:
            yol = journal.KOK / "takilma.log"
            yol.parent.mkdir(parents=True, exist_ok=True)
            f = open(yol, "a", encoding="utf-8")
            f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} oturum basladi; "
                    f"asagida 'Timeout' varsa arayuz thread'i {ESIK_SN:.0f} sn "
                    f"yanit vermedi =====\n")
            f.flush()
        except Exception:
            return
        while True:
            faulthandler.dump_traceback_later(ESIK_SN, repeat=False, file=f)
            try:
                pencere.evaluate_js("1")
            except Exception:
                pass
            time.sleep(3.0)

    threading.Thread(target=_dongu, daemon=True, name="pevrai-bekci").start()


def bagimliliklari_denetle() -> str | None:
    """Gerekli paketlerin kurulu olup olmadığını doğrular."""
    import importlib.util

    eksik = [ad for ad in ("mcp", "httpx")
             if importlib.util.find_spec(ad) is None]
    if not eksik:
        return None
    venv = PROJE_KOKU / ".venv" / "Scripts" / "python.exe"
    ipucu = (f"Proje sanal ortamiyla baslat (proje kokunden):\n  {venv} -m pevrai"
             if venv.exists() else
             f"Kur: {sys.executable} -m pip install -r requirements.txt")
    return (f"Eksik paket(ler): {', '.join(eksik)}\n"
            f"Etkin yorumlayici: {sys.executable}\n  {ipucu}")
