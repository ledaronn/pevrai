"""Güvenlik kuralları ve saf karar fonksiyonları.

Diske dokunmaz, policy.toml okumaz. Politika sınıfı tarafından ve testler
tarafından bağımsız karar mekanizması olarak kullanılır.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from pevrai.ceviri import t

ALLOW = "ALLOW"
ASK = "ASK"
DENY = "DENY"


@dataclass
class Karar:
    sonuc: str                 # ALLOW / ASK / DENY
    gerekce: str
    yol: Path | None = None    # çözülmüş ve doğrulanmış yol; araca bu verilir


def windows_ad_tuzagi(yol: Path) -> str | None:
    """Bu cozulmus yol, Windows'un BASKA bir dosyaya cevirecegi bir ad tasiyor mu?"""
    for parca in yol.parts:
        if "\x00" in parca:
            return "yol gomulu NUL bayti iceriyor"
        if len(parca) > 1 and parca.rstrip(". ") != parca and not parca.endswith(":\\"):
            return (f"'{parca}' adi nokta ya da bosluk ile bitiyor; Windows bunu "
                    f"acarken yutar ve BASKA bir dosyaya ({parca.rstrip('. ')}) iner")
    return None


def acma_klasoru_ihlali(klasor: Path, yazma_kokleri: Iterable[Path], proje_koku: Path) -> str | None:
    """Acma klasoru ajanin yazabildigi bir yerle kesisiyor mu?"""
    for w in yazma_kokleri:
        if klasor == w or w in klasor.parents or klasor in w.parents:
            return t("Açma klasörü ({klasor}) ajanın yazabildiği bir yerle kesişiyor ({yazma}). "
                     "Ajan oraya kısayol yazıp açabilirdi; ayrı bir klasör seç.", klasor=klasor, yazma=w)
    from pevrai import DONMUS, KAYNAK_KOK, PAKET
    korunan = [PAKET, Path(proje_koku) / "config"] + ([KAYNAK_KOK] if DONMUS else [])
    for k in korunan:
        if klasor == k or k in klasor.parents:
            return t("Açma klasörü ({klasor}) Pevrai'nın kendi klasörünün içinde olamaz.", klasor=klasor)
    return None


def kod_kokleri(proje_koku: Path) -> list[Path]:
    """Korunacak kokler."""
    from pevrai import DONMUS, KAYNAK_KOK
    kokler = [Path(proje_koku)]
    if DONMUS:
        try:
            kokler.append(KAYNAK_KOK.resolve())
        except OSError:
            pass
    return kokler


def korunan_yol_ihlali(yazma_kokleri: Iterable[Path], kod_koku: Path) -> str | None:
    """Bu yazma koku listesi ajanin kendi davranisini degistirmesine izin veriyor mu?"""
    def coz(y: Path) -> Path:
        try:
            return Path(os.path.realpath(y))
        except (OSError, ValueError):
            return Path(y)
    kod_koku = coz(Path(kod_koku))
    yazma_kokleri = [coz(Path(y)) for y in yazma_kokleri]
    korunan = {"kaynak kodu": kod_koku, "config klasoru": kod_koku / "config"}
    for etiket, hedef in korunan.items():
        for yazilabilir in yazma_kokleri:
            if hedef == yazilabilir or yazilabilir in hedef.parents:
                return (f"Pevrai'nin {etiket} ({hedef}) yazma kokunun ICINDE: "
                        f"{yazilabilir}. Bu yerlesimde ajan kendi izin kapisini ya da "
                        f"kendi sistem talimatini degistirebilir.")
    return None


def tavan_karari(rol: str,
                  sayaclar: Mapping[str, int],
                  tavanlar: Mapping[str, int]) -> tuple[int, int] | None:
    """Bu rol icin gunluk istek tavani doldu mu?"""
    tavan = tavanlar.get(rol, 0)
    if not tavan:
        return None
    sayi = sayaclar.get(rol, 0)
    return (sayi, tavan) if sayi >= tavan else None


TUR_TAVANI = {"READ": 12, "WRITE": 5, "EXEC": 3, "NETWORK": 3, "DESTRUCTIVE": 2}

PROFIL_ALANLARI = {"araclar", "yazma_koklari", "mod", "azami_adim", "azami_devam"}
AJAN_ALANLARI = {"saglayici", "model", "anahtar_yuvasi", "rol", "taban_url", "baglanti", "renk", "gorunum"}
ESKI_BAGLANTI_KIMLIGI = "ana"
AJAN_AD_KALIBI = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
BAGLANTI_ALANLARI = {"ad", "saglayici", "taban_url", "modeller", "anahtar_yuvasi"}
BAGLANTI_KALIBI = re.compile(r"^[a-z0-9][a-z0-9_-]{0,19}$")


def tur_karari(risk: str,
               tur_sayaci: Mapping[str, int],
               tur_tavani: Mapping[str, int] = TUR_TAVANI) -> tuple[int, int] | None:
    """Bu TURDA bu risk seviyesinden yapilan cagri sinira carpti mi?"""
    tavan = tur_tavani.get(risk, 5)
    sayi = tur_sayaci.get(risk, 0)
    return (sayi, tavan) if sayi > tavan else None


def butce_karari(harcanan: int, butce: int) -> tuple[int, int] | None:
    """Bu GOREV icin istek butcesi doldu mu?"""
    if not butce:
        return None
    return (harcanan, butce) if harcanan >= butce else None


def durum_karari(adim: int, azami_adim: int, *,
                 cagri_tavaninda_mi: bool = False,
                 butce_doldu_mu: bool = False,
                 model_bitirdi_mi: bool = False) -> str:
    """Ajan döngüsünün durum kararını verir: 'bitti', 'durum_yaz', 'devam'."""
    if model_bitirdi_mi:
        return "bitti"
    if cagri_tavaninda_mi or butce_doldu_mu:
        return "durum_yaz"
    if azami_adim > 0 and adim >= azami_adim:
        return "durum_yaz"
    return "devam"


def devam_karari(devam_sayisi: int, azami_devam: int, *,
                 yeni_yazma_var_mi: bool,
                 kota_dolu_mu: bool) -> str:
    """Kendiliğinden devam kararını verir: 'devam', 'dur_kota', 'dur_sinir', 'dur_ilerleme_yok'."""
    if kota_dolu_mu:
        return "dur_kota"
    if azami_devam <= 0 or devam_sayisi >= azami_devam:
        return "dur_sinir"
    if not yeni_yazma_var_mi:
        return "dur_ilerleme_yok"
    return "devam"


def kok_karari(onceki: Iterable[str | Path], simdiki: Iterable[str | Path]) -> str | None:
    """Durum dosyasındaki yazma kökleri şimdiki köklerle (küme eşitliği) aynı mı?
    Aynıysa None, değişmişse açıklayıcı hata metni döndürür."""
    try:
        o_set = {str(Path(p).expanduser().resolve()).lower() for p in onceki}
        s_set = {str(Path(p).expanduser().resolve()).lower() for p in simdiki}
    except Exception:
        o_set = {str(p).lower() for p in onceki}
        s_set = {str(p).lower() for p in simdiki}

    if o_set == s_set:
        return None

    return (
        f"Yazma kökleri değişmiş (önceki: {sorted(str(p) for p in onceki)}, "
        f"şimdiki: {sorted(str(p) for p in simdiki)}). Güvenlik gereği devam edilemez."
    )
