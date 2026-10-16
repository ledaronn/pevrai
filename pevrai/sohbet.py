"""Sohbetlerin diske kaydi.

Bicim BIZIM: model kutuphanesinin nesneleri oldugu gibi yazilmaz, kendi
sozluk bicimimize cevrilir (A2 karari). Gerekcesi: SDK surumu degisince eski
sohbet dosyalari okunamaz hale gelmesin.

Bedeli: arac cagrisi/sonuc zincirini yeniden kurmak bize kaliyor ve orada
yapilacak bir hata modele BOZUK bir gecmis verirdi. Bu yuzden yuklerken zincir
dogrulaniyor: eslesmeyen bir cagri/sonuc gorulurse gecmis o noktadan KESILIR
ve kullaniciya soylenir. Sessizce bozuk baglam yuklemektense acikca kaybetmek.

NE KAYDEDILIR: kullanici mesajlari, ajan yanitlari, arac cagrilari ve arac
SONUCLARI — yani okunan dosyalarin ve web sayfalarinin tam metni. Kullanici
bunu bilerek secti (bkz. arayuzdeki kenar cubugu notu). Dosyalar ~/.vekil
altinda, journal yedekleriyle ayni yerde.

NE KAYDEDILMEZ: tarayici ekran kareleri (gui_kopru arsive hic koymuyor).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pevrai import journal
KOK = journal.KOK / "sohbetler"
BICIM_SURUMU = 1
AD_KALIBI = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _hazirla() -> None:
    KOK.mkdir(parents=True, exist_ok=True)


def _yol(kimlik: str) -> Path | None:
    """Kimlik dosya adina cevrilir. Yol enjeksiyonuna kapali: sadece basit adlar."""
    if not AD_KALIBI.match(kimlik or ""):
        return None
    return KOK / f"{kimlik}.json"


# ---------------------------------------------------------------------------
# Model gecmisi <-> sozluk
# ---------------------------------------------------------------------------

def _parca_sozluge(parca: Any) -> dict | None:
    """Tek bir Part -> sozluk. Taninmayan parca None doner ve atlanir."""
    metin = getattr(parca, "text", None)
    if metin:
        return {"tip": "metin", "metin": metin}

    cagri = getattr(parca, "function_call", None)
    if cagri is not None:
        return {"tip": "cagri",
                "ad": getattr(cagri, "name", "") or "",
                "args": dict(getattr(cagri, "args", None) or {}),
                "id": getattr(cagri, "id", None)}

    cevap = getattr(parca, "function_response", None)
    if cevap is not None:
        return {"tip": "sonuc",
                "ad": getattr(cevap, "name", "") or "",
                "cevap": dict(getattr(cevap, "response", None) or {}),
                "id": getattr(cevap, "id", None)}
    return None


def _content_sozluge(icerik: Any) -> dict:
    # Gecmis artik BIZIM bicimde (pevrai.model.taban): sozluk gelirse aynen.
    # SDK nesnesi (eski yol) gelirse cevrilir — geriye donuk uyumluluk.
    if isinstance(icerik, dict):
        return {"rol": icerik.get("rol", "user") or "user",
                "parcalar": [dict(p) for p in icerik.get("parcalar", []) if isinstance(p, dict)]}
    parcalar = []
    for parca in (getattr(icerik, "parts", None) or []):
        d = _parca_sozluge(parca)
        if d is not None:
            parcalar.append(d)
    return {"rol": getattr(icerik, "role", "") or "user", "parcalar": parcalar}


def _sozluk_contente(d: dict, types: Any) -> Any:
    parcalar = []
    for p in d.get("parcalar", []):
        tip = p.get("tip")
        if tip == "metin":
            parcalar.append(types.Part.from_text(text=p.get("metin", "")))
        elif tip == "cagri":
            cagri = types.FunctionCall(name=p.get("ad", ""), args=p.get("args") or {})
            if p.get("id"):
                cagri.id = p["id"]
            parcalar.append(types.Part(function_call=cagri))
        elif tip == "sonuc":
            parcalar.append(types.Part.from_function_response(
                name=p.get("ad", ""), response=p.get("cevap") or {}))
    return types.Content(role=d.get("rol", "user"), parts=parcalar)


def zinciri_dogrula(sozlukler: list[dict]) -> tuple[list[dict], str | None]:
    """Cagri/sonuc zincirini dogrular; bozuk kuyrugu keser.

    Kural: model bir tur icinde n arac cagirir, sonraki icerik(ler) o n sonucu
    tasimak zorundadir. Sonuclari eksik bir tur baglamda kalirsa bir sonraki
    model cagrisi hata verir. Bu yuzden "butun" oldugu bilinen SON noktaya
    kadar kesiyoruz.
    """
    if not sozlukler:
        return [], None

    # Bas: ilk kullanici metniyle baslamali (yarim bir turla baslayan gecmis gecersiz).
    bas = 0
    for i, d in enumerate(sozlukler):
        if d.get("rol") == "user" and any(p.get("tip") == "metin" for p in d.get("parcalar", [])):
            bas = i
            break
    else:
        return [], "Gecmiste kullanici mesaji bulunamadi, baglam yuklenmedi."

    calisan = sozlukler[bas:]

    bekleyen = 0
    guvenli = 0          # zincirin butun oldugu son indis (dahil)
    for i, d in enumerate(calisan):
        for p in d.get("parcalar", []):
            if p.get("tip") == "cagri":
                bekleyen += 1
            elif p.get("tip") == "sonuc":
                bekleyen -= 1
        if bekleyen <= 0:
            bekleyen = 0
            guvenli = i + 1

    atilan = (bas) + (len(calisan) - guvenli)
    kirpik = calisan[:guvenli]
    if not kirpik:
        return [], "Gecmisin tamami yarim kalmis, baglam yuklenmedi."
    if atilan:
        return kirpik, (f"Gecmisin sonundaki {atilan} kayit yarim kalmisti "
                        f"(arac cagrisinin sonucu eksik), baglamdan cikarildi.")
    return kirpik, None


# ---------------------------------------------------------------------------
# Disk
# ---------------------------------------------------------------------------

INDEKS_DOSYASI = ".indeks"


def _indeks_yolu() -> Path:
    return KOK / INDEKS_DOSYASI


def _indeks_oku() -> dict[str, dict]:
    yol = _indeks_yolu()
    if not yol.exists():
        return {}
    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
        return veri.get("sohbetler", {}) if isinstance(veri, dict) else {}
    except Exception:
        return {}


def _indeks_yaz(indeks: dict[str, dict]) -> None:
    try:
        _hazirla()
        yol = _indeks_yolu()
        if not indeks:
            if yol.exists():
                yol.unlink()
            return
        gecici = yol.with_suffix(".yeni")
        veri = {"surum": BICIM_SURUMU, "sohbetler": indeks}
        gecici.write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
        gecici.replace(yol)
    except Exception:
        pass


def _indeks_guncelle(kimlik: str, baslik: str, guncelleme: str, olay_sayisi: int,
                     proje_baglami: dict | None, dosya: Path) -> None:
    try:
        indeks = _indeks_oku()
        stat = dosya.stat()
        indeks[kimlik] = {
            "id": kimlik,
            "baslik": baslik,
            "guncelleme": guncelleme,
            "olay": olay_sayisi,
            "proje_baglami": proje_baglami,
            "boyut": stat.st_size,
            "mtime": stat.st_mtime,
        }
        _indeks_yaz(indeks)
    except Exception:
        pass


def _indeks_sil(kimlik: str) -> None:
    try:
        indeks = _indeks_oku()
        if kimlik in indeks:
            del indeks[kimlik]
            _indeks_yaz(indeks)
    except Exception:
        pass


def kaydet(kimlik: str, baslik: str, arsiv: list[dict], gecmis: list[Any],
           guncelleme: str | None = None,
           proje_baglami: dict | None = None) -> str | None:
    """Sohbeti diske yazar. Hata varsa metin dondurur (gorevi bozmaz).

    guncelleme: cagiranin (gui_kopru) belleginde tuttugu son degisiklik ani.
    Verilmezse yazma ani yazilir. Verilmesi onemli: kapanista butun sohbetler
    arka arkaya kaydediliyor; hepsine "simdi" yazilsaydi hepsi ayni anda
    guncellenmis gorunur ve kenar cubugundaki sira her kapanista bozulurdu.
    """
    yol = _yol(kimlik)
    if yol is None:
        return f"Gecersiz sohbet kimligi: {kimlik!r}"
    try:
        _hazirla()
        guncel_an = guncelleme or datetime.now().isoformat(timespec="seconds")
        veri = {
            "surum": BICIM_SURUMU,
            "id": kimlik,
            "baslik": baslik,
            "guncelleme": guncel_an,
            "arsiv": arsiv,
            "gecmis": [_content_sozluge(c) for c in gecmis],
            "proje_baglami": proje_baglami,
        }
        gecici = yol.with_suffix(".json.yeni")
        gecici.write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
        gecici.replace(yol)     # atomik: yarim yazilmis dosya birakmaz
        _indeks_guncelle(kimlik, baslik, guncel_an, len(arsiv), proje_baglami, yol)
        return None
    except Exception as e:
        return f"Sohbet kaydedilemedi ({type(e).__name__}: {e})"


def yukle_tek(kimlik: str) -> dict | None:
    """Tek bir sohbet dosyasini tam okur ve dogrular."""
    yol = _yol(kimlik)
    if yol is None or not yol.exists():
        return None
    try:
        stat = yol.stat()
        dosya_zamani = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
        veri = json.loads(yol.read_text(encoding="utf-8"))
        guncelleme = veri.get("guncelleme") or dosya_zamani
        if veri.get("surum") != BICIM_SURUMU:
            return {
                "id": veri.get("id", yol.stem),
                "baslik": veri.get("baslik", ""),
                "guncelleme": guncelleme,
                "arsiv": veri.get("arsiv", []),
                "gecmis": [],
                "uyari": "Sohbet dosyasi eski bir bicimde. Metin acildi ama "
                         "baglam yuklenmedi: buradan devam edersen ajan "
                         "onceki konusmayi hatirlamaz.",
                "proje_baglami": veri.get("proje_baglami"),
            }
        gecmis, uyari = zinciri_dogrula(veri.get("gecmis", []))
        return {
            "id": veri.get("id", yol.stem),
            "baslik": veri.get("baslik", ""),
            "guncelleme": guncelleme,
            "arsiv": veri.get("arsiv", []),
            "gecmis": gecmis,
            "uyari": uyari,
            "proje_baglami": veri.get("proje_baglami"),
        }
    except Exception as e:
        return {
            "id": yol.stem,
            "baslik": yol.stem,
            "guncelleme": dosya_zamani,
            "arsiv": [],
            "gecmis": [],
            "uyari": f"Sohbet dosyasi okunamadi ({type(e).__name__}), bos acildi.",
        }


def yukle_indeks() -> list[dict]:
    """Kayitli sohbetlerin hafif indeksini doner. Dosyalarin tamamini okumaz.

    Her ogede: id, baslik, guncelleme, olay, proje_baglami, boyut.
    """
    if not KOK.exists():
        return []

    mevcut_indeks = _indeks_oku()
    indeks_degisti = False
    guncel_indeks: dict[str, dict] = {}
    sonuclar: list[dict] = []

    dosyalar = [p for p in KOK.glob("*.json") if not p.name.startswith("_")]
    dosyalar.sort(key=lambda p: p.stat().st_mtime)

    for yol in dosyalar:
        kimlik = yol.stem
        try:
            stat = yol.stat()
        except OSError:
            continue

        kayit = mevcut_indeks.get(kimlik)
        if kayit and kayit.get("mtime") == stat.st_mtime and kayit.get("boyut") == stat.st_size:
            guncel_indeks[kimlik] = kayit
            sonuclar.append(dict(kayit))
            continue

        indeks_degisti = True
        dosya_zamani = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
        try:
            veri = json.loads(yol.read_text(encoding="utf-8"))
            baslik = veri.get("baslik") or kimlik
            guncelleme = veri.get("guncelleme") or dosya_zamani
            olay_sayisi = len(veri.get("arsiv", []))
            proje = veri.get("proje_baglami")
        except Exception:
            baslik = kimlik
            guncelleme = dosya_zamani
            olay_sayisi = 0
            proje = None

        yeni_kayit = {
            "id": kimlik,
            "baslik": baslik,
            "guncelleme": guncelleme,
            "olay": olay_sayisi,
            "proje_baglami": proje,
            "boyut": stat.st_size,
            "mtime": stat.st_mtime,
        }
        guncel_indeks[kimlik] = yeni_kayit
        sonuclar.append(dict(yeni_kayit))

    if indeks_degisti or len(guncel_indeks) != len(mevcut_indeks):
        _indeks_yaz(guncel_indeks)

    return sonuclar


def yukle_hepsi(hafif: bool = False) -> list[dict]:
    """Kayitli sohbetleri okur.
    hafif=True ise yalnizca indeks bilgilerini doner.
    hafif=False (varsayilan) ise eski sozlesmeyle tum dosyalari tam yukler.
    """
    if hafif:
        return yukle_indeks()

    if not KOK.exists():
        return []
    cikti = []
    dosyalar = [p for p in KOK.glob("*.json") if not p.name.startswith("_")]
    dosyalar.sort(key=lambda p: p.stat().st_mtime)
    for yol in dosyalar:
        tek = yukle_tek(yol.stem)
        if tek:
            cikti.append(tek)
    return cikti


def sozlukleri_contente(sozlukler: list[dict], types: Any = None) -> list[Any]:
    """types verilirse SDK nesnelerine cevirir (eski yol); verilmezse gecmis
    zaten sozluk bicimi — kopyalanip doner (pevrai.model bu bicimi konusur)."""
    if types is None:
        return [_content_sozluge(d) for d in sozlukler]
    return [_sozluk_contente(d, types) for d in sozlukler]


def sil(kimlik: str) -> bool:
    """Sohbet dosyasini GERCEKTEN siler (cop kutusuna tasimaz).

    Bilincli istisna: cop kutusu kurali kullanicinin dosyalari icin. Bu dosya
    ajanin urettigi bir kayit ve icinde hassas icerik olabilir; "sil" dedigi
    yerde diskte kalmasi kotu olurdu.
    """
    yol = _yol(kimlik)
    if yol is None or not yol.exists():
        return False
    try:
        yol.unlink()
        _indeks_sil(kimlik)
        return True
    except OSError:
        return False
