"""config/arayuz.toml okuma ve yazma fonksiyonlari.

Zararsiz gorunum ve davranis ayarlari. Dosya yoksa ya da bozuksa
varsayilanlara dusulur.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import Any

from pevrai import PROJE_KOKU

ARAYUZ_YOL = PROJE_KOKU / "config" / "arayuz.toml"

ARAYUZ_VARSAYILAN: dict[str, dict[str, Any]] = {
    "genel": {"dil": "en", "gelismis_ayarlar": False, "kurulum_tamam": False, "guncellemeleri_denetle": True},
    "gorunum": {"tema": "koyu", "animasyon": "tam", "mesaj_genisligi": "dengeli", "ekip_gorunumu": "ofis", "yazi_boyutu": "normal"},
    "sohbet": {"gecmis_koru": True, "otomatik_kaydirma": True, "sesli_giris": False},
    "gelismis": {"teknik_ayrinti_acik": False, "test_modu": False},
}

ARAYUZ_SECENEK: dict[tuple[str, str], tuple[Any, ...]] = {
    ("genel", "dil"): ("tr", "en"),
    ("genel", "gelismis_ayarlar"): (True, False),
    ("genel", "kurulum_tamam"): (True, False),
    ("genel", "guncellemeleri_denetle"): (True, False),
    ("gorunum", "tema"): ("koyu", "acik", "sistem"),
    ("gorunum", "animasyon"): ("tam", "azaltilmis", "kapali"),
    ("gorunum", "mesaj_genisligi"): ("dar", "dengeli", "genis"),
    ("gorunum", "ekip_gorunumu"): ("ofis", "kart"),
    ("gorunum", "yazi_boyutu"): ("kucuk", "normal", "buyuk", "cok_buyuk"),
    ("sohbet", "gecmis_koru"): (True, False),
    ("sohbet", "otomatik_kaydirma"): (True, False),
    ("sohbet", "sesli_giris"): (True, False),
    ("gelismis", "teknik_ayrinti_acik"): (True, False),
    ("gelismis", "test_modu"): (True, False),
}


def _arayuz_yolu() -> Path:
    mod = sys.modules.get("pevrai.ayarlar")
    if mod and hasattr(mod, "ARAYUZ_YOL"):
        return getattr(mod, "ARAYUZ_YOL")
    return ARAYUZ_YOL


def _toml_deger(d: Any) -> str:
    if isinstance(d, bool):
        return "true" if d else "false"
    if isinstance(d, (int, float)):
        return str(d)
    return '"' + str(d).replace('"', '\\"') + '"'


def _atomik_yaz(yol: Path, metin: str) -> None:
    """Gecici dosyaya yaz, sonra yerine koy. Yarim yazilmis dosya birakmaz."""
    gecici = yol.with_name(yol.name + ".yeni")
    gecici.write_text(metin, encoding="utf-8")
    gecici.replace(yol)


def arayuz_oku() -> dict[str, dict[str, Any]]:
    """Arayuz ayarlarini doner. Dosya yoksa ya da BOZUKSA varsayilanlar."""
    sonuc = {b: dict(a) for b, a in ARAYUZ_VARSAYILAN.items()}
    yol = _arayuz_yolu()
    try:
        if not yol.exists():
            return sonuc
        ham = tomllib.loads(yol.read_text(encoding="utf-8"))
    except Exception:
        return sonuc
    for bolum, alanlar in sonuc.items():
        gelen = ham.get(bolum)
        if not isinstance(gelen, dict):
            continue
        for anahtar in list(alanlar):
            deger = gelen.get(anahtar)
            if deger is not None and deger in ARAYUZ_SECENEK.get((bolum, anahtar), ()):
                alanlar[anahtar] = deger
    return sonuc


def arayuz_yaz(bolum: str, anahtar: str, deger: Any) -> str | None:
    """Tek bir arayuz ayarini yazar. Hata varsa metin doner, yoksa None."""
    if (bolum, anahtar) not in ARAYUZ_SECENEK:
        return f"Taninmayan ayar: {bolum}.{anahtar}"
    if deger not in ARAYUZ_SECENEK[(bolum, anahtar)]:
        izinli = ", ".join(str(x) for x in ARAYUZ_SECENEK[(bolum, anahtar)])
        return f"'{deger}' gecersiz. Izinli: {izinli}"

    mevcut = arayuz_oku()
    mevcut[bolum][anahtar] = deger
    satirlar = ["# arayuz.toml — Pevrai arayuz ayarlari.",
                "# Bu dosya arayuzden yazilir; elle de duzenlenebilir.",
                "# Bozulursa varsayilanlara dusulur, uygulama acilmaya devam eder.", ""]
    for b, alanlar in mevcut.items():
        satirlar.append(f"[{b}]")
        for a, d in alanlar.items():
            satirlar.append(f"{a} = {_toml_deger(d)}")
        satirlar.append("")
    yol = _arayuz_yolu()
    try:
        yol.parent.mkdir(parents=True, exist_ok=True)
        _atomik_yaz(yol, "\n".join(satirlar))
    except OSError as e:
        return f"Yazilamadi: {e}"
    return None
