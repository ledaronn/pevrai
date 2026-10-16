"""Kullanici gorev/istem sablonlari: yerel, atomik JSON deposu ve komutlar.toml birlestirici.

Yerlesik komutlar config/komutlar.toml dosyasindan okunur (salt okunur).
Kullanicinin kaydettigi ozel gorev sablonlari ~/.vekil/sablonlar.json icinde
saklanir; boylece git izli dosyalara dokunulmaz ve testlerde PEVRAI_VEKIL_KOK
ile tam yalitim saglanir.
"""
from __future__ import annotations

import json
import re
import threading
import tomllib
from pathlib import Path
from typing import Any

from pevrai import KAYNAK_KOK, PROJE_KOKU, journal
from pevrai.ceviri import t

YOL = journal.KOK / "sablonlar.json"
_KILIT = threading.RLock()

YASAK_ADLAR = frozenset({"ekip", "gecmis", "siteler", "yeni"})
AZAMI_SABLON_SAYISI = 100
AZAMI_SABLON_UZUNLUK = 4000
AZAMI_ACIKLAMA_UZUNLUK = 160

_TR_HARITA = str.maketrans("çğıöşüÇĞİIÖŞÜ ", "cgiosucgiiosu-")
_AD_KALIBI = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def ad_temizle(ad: str) -> str:
    """Sablon adini temizler: bastaki '/' atilir, Turkce harfler ASCII'ye cevrilir."""
    ham = str(ad or "").strip()
    while ham.startswith("/"):
        ham = ham[1:].strip()
    temiz = ham.translate(_TR_HARITA).lower()
    temiz = re.sub(r"-{2,}", "-", temiz).strip("-_")
    return temiz


def oku_ozel() -> list[dict[str, Any]]:
    """Kullanicinin kaydettigi ozel sablonlari doner."""
    with _KILIT:
        if not YOL.exists():
            return []
        try:
            veri = json.loads(YOL.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(veri, list):
            return []
        sonuc: list[dict[str, Any]] = []
        for oge in veri:
            if not isinstance(oge, dict):
                continue
            ad = ad_temizle(str(oge.get("ad") or ""))
            sablon = str(oge.get("sablon") or "").strip()
            aciklama = str(oge.get("aciklama") or "").strip()
            if ad and _AD_KALIBI.fullmatch(ad) and sablon and ad not in YASAK_ADLAR:
                sonuc.append({
                    "ad": ad,
                    "aciklama": aciklama[:AZAMI_ACIKLAMA_UZUNLUK],
                    "sablon": sablon[:AZAMI_SABLON_UZUNLUK],
                    "ozel": True,
                })
        return sonuc


def _atomik_yaz(liste: list[dict[str, Any]]) -> None:
    YOL.parent.mkdir(parents=True, exist_ok=True)
    gecici = YOL.with_suffix(".json.yeni")
    kayit = [{"ad": x["ad"], "aciklama": x.get("aciklama", ""), "sablon": x["sablon"]} for x in liste]
    gecici.write_text(json.dumps(kayit, ensure_ascii=False, indent=2), encoding="utf-8")
    gecici.replace(YOL)


def yerlesik_oku(kok: Path | None = None) -> tuple[list[dict[str, Any]], str | None]:
    """config/komutlar.toml dosyasindaki yerlesik komutlari okur."""
    hedef_kok = kok or PROJE_KOKU
    yol = hedef_kok / "config" / "komutlar.toml"
    if not yol.exists() and kok is None:
        yedek = KAYNAK_KOK / "config" / "komutlar.toml"
        if yedek.exists():
            yol = yedek
    if not yol.exists():
        return [], None
    try:
        veri = tomllib.loads(yol.read_text(encoding="utf-8"))
    except Exception as e:
        return [], f"komutlar.toml okunamadi: {e}"
    komutlar = veri.get("komut", [])
    if not isinstance(komutlar, list):
        return [], None
    return [dict(k) for k in komutlar if isinstance(k, dict) and k.get("ad")], None


def listele(kok: Path | None = None) -> tuple[list[dict[str, Any]], str | None]:
    """Yerlesik komutlar ile ozel kullanici sablonlarini birlestirir."""
    yerlesik, hata = yerlesik_oku(kok)
    if hata:
        return [], hata
    ozeller = oku_ozel()
    ozel_harita = {x["ad"]: x for x in ozeller}
    birlesik: list[dict[str, Any]] = []
    gorulen: set[str] = set()
    for k in yerlesik:
        ad = str(k.get("ad") or "")
        if ad in ozel_harita and ad not in YASAK_ADLAR:
            birlesik.append(ozel_harita[ad])
            gorulen.add(ad)
        else:
            birlesik.append(k)
            gorulen.add(ad)
    for x in ozeller:
        if x["ad"] not in gorulen:
            birlesik.append(x)
            gorulen.add(x["ad"])
    return birlesik, None


def kaydet(ad: str, sablon: str, aciklama: str = "") -> str | None:
    """Ozel gorev sablonu ekler veya gunceller. Basariliysa None, hatada mesaj doner."""
    temiz_ad = ad_temizle(ad)
    if not temiz_ad or not _AD_KALIBI.fullmatch(temiz_ad):
        return t("Şablon adı yalnızca küçük harf, rakam ve tire içerebilir (en fazla 40 karakter).")
    if temiz_ad in YASAK_ADLAR:
        return t("Bu komut adı sistem tarafından kullanılıyor.")
    temiz_sablon = str(sablon or "").strip()
    if not temiz_sablon:
        return t("Şablon metni boş olamaz.")
    if len(temiz_sablon) > AZAMI_SABLON_UZUNLUK:
        return t("Şablon metni çok uzun (en fazla {azami} karakter).", azami=AZAMI_SABLON_UZUNLUK)
    temiz_aciklama = str(aciklama or "").strip()
    if len(temiz_aciklama) > AZAMI_ACIKLAMA_UZUNLUK:
        return t("Şablon açıklaması çok uzun (en fazla {azami} karakter).", azami=AZAMI_ACIKLAMA_UZUNLUK)

    with _KILIT:
        mevcut = oku_ozel()
        yeni_oge = {
            "ad": temiz_ad,
            "aciklama": temiz_aciklama,
            "sablon": temiz_sablon,
            "ozel": True,
        }
        guncellendi = False
        for i, oge in enumerate(mevcut):
            if oge["ad"] == temiz_ad:
                mevcut[i] = yeni_oge
                guncellendi = True
                break
        if not guncellendi:
            if len(mevcut) >= AZAMI_SABLON_SAYISI:
                return t("En fazla {azami} özel şablon kaydedilebilir.", azami=AZAMI_SABLON_SAYISI)
            mevcut.append(yeni_oge)
        try:
            _atomik_yaz(mevcut)
        except OSError as e:
            return f"Yazilamadi: {e}"
    return None


def sil(ad: str) -> str | None:
    """Ozel gorev sablonunu siler. Basariliysa None, hatada mesaj doner."""
    temiz_ad = ad_temizle(ad)
    if not temiz_ad:
        return t("Silinecek özel şablon bulunamadı.")
    with _KILIT:
        mevcut = oku_ozel()
        yeni = [x for x in mevcut if x["ad"] != temiz_ad]
        if len(yeni) == len(mevcut):
            return t("Silinecek özel şablon bulunamadı.")
        try:
            _atomik_yaz(yeni)
        except OSError as e:
            return f"Yazilamadi: {e}"
    return None
