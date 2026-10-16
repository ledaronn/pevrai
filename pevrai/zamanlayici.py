"""zamanlayici.py — Yerel zamanlanmış ve tekrarlayan görev yöneticisi (Faz 5.5).

Görev tanımları kullanıcının yerel dizininde (`~/.vekil/zamanlanmis_gorevler.json`,
yani `journal.KOK` altında, `policy.toml` yazma köklerinin dışında) atomik olarak
saklanır; ajan kendi zamanlanmış görevlerini değiştiremez.

Güvenlik ve kota sözleşmesi:
- Zamanlanmış görevler tetiklendiğinde standart `Kopru.gorev_baslat` -> `vekil_v0.calistir`
  hattından (`profil=None` ile) geçer.
- `gate.py` onay kapısı (ALLOW / ASK / DENY) ve `journal.kota_ayir` / adım / çağrı /
  bütçe sınırları kesinlikle atlanmaz.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from pevrai import journal
from pevrai.ceviri import t

YOL: Path = journal.KOK / "zamanlanmis_gorevler.json"
SIKLIKLAR = ("gunluk", "haftalik", "bir_kez")
MODLAR = ("hizli", "dengeli", "derin", "azami")
SAAT_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
TARIH_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_KILIT = threading.Lock()


def _atomik_yaz(yol: Path, veri: list[dict[str, Any]]) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_name(yol.name + ".yeni")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gecici.replace(yol)


def _saat_coz(saat_str: str) -> time | None:
    m = SAAT_RE.match((saat_str or "").strip())
    if not m:
        return None
    return time(int(m.group(1)), int(m.group(2)))


def _tarih_coz(tarih_str: str) -> date | None:
    m = TARIH_RE.match((tarih_str or "").strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _oku_ham() -> list[dict[str, Any]]:
    if not YOL.exists():
        return []
    try:
        veri = json.loads(YOL.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(veri, list):
        return []
    temiz: list[dict[str, Any]] = []
    for oge in veri:
        if not isinstance(oge, dict):
            continue
        gid = str(oge.get("id") or "").strip()
        ad = str(oge.get("ad") or "").strip()
        gorev = str(oge.get("gorev") or "").strip()
        siklik = str(oge.get("siklik") or "gunluk").strip()
        saat = str(oge.get("saat") or "09:00").strip()
        mod = str(oge.get("mod") or "dengeli").strip()
        if not gid or not ad or not gorev:
            continue
        if siklik not in SIKLIKLAR or _saat_coz(saat) is None or mod not in MODLAR:
            continue
        gun = oge.get("gun", 0)
        gun_int = int(gun) if isinstance(gun, int) and not isinstance(gun, bool) and 0 <= gun <= 6 else 0
        tarih = str(oge.get("tarih") or "").strip()
        if siklik == "bir_kez" and _tarih_coz(tarih) is None:
            continue
        temiz.append({
            "id": gid,
            "ad": ad[:60],
            "gorev": gorev[:4000],
            "siklik": siklik,
            "saat": saat,
            "gun": gun_int,
            "tarih": tarih,
            "mod": mod,
            "etkin": bool(oge.get("etkin", True)),
            "son_calisma": str(oge["son_calisma"]) if oge.get("son_calisma") else None,
            "calisma_sayisi": int(oge.get("calisma_sayisi") or 0),
        })
    return temiz


def sonraki_calisma_zamani(kayit: dict[str, Any], simdi: datetime | None = None) -> datetime | None:
    """Görevin bir sonraki planlanan çalışma zamanını döndürür."""
    if not kayit.get("etkin", True):
        return None
    ref = simdi or datetime.now()
    saat_obj = _saat_coz(str(kayit.get("saat") or ""))
    if saat_obj is None:
        return None
    siklik = kayit.get("siklik")
    son_str = kayit.get("son_calisma")
    son_dt: datetime | None = None
    if isinstance(son_str, str) and son_str:
        try:
            son_dt = datetime.fromisoformat(son_str)
        except ValueError:
            son_dt = None

    if siklik == "bir_kez":
        t_obj = _tarih_coz(str(kayit.get("tarih") or ""))
        if t_obj is None:
            return None
        hedef = datetime.combine(t_obj, saat_obj)
        if son_dt is not None and son_dt >= hedef:
            return None
        return hedef

    if siklik == "gunluk":
        bugun_hedef = datetime.combine(ref.date(), saat_obj)
        if ref >= bugun_hedef and (son_dt is None or son_dt < bugun_hedef):
            return bugun_hedef
        if ref < bugun_hedef and (son_dt is None or son_dt < bugun_hedef):
            return bugun_hedef
        return datetime.combine(ref.date() + timedelta(days=1), saat_obj)

    if siklik == "haftalik":
        hedef_gun = int(kayit.get("gun", 0))
        fark = (hedef_gun - ref.weekday()) % 7
        aday_tarih = ref.date() + timedelta(days=fark)
        aday = datetime.combine(aday_tarih, saat_obj)
        if fark == 0 and son_dt is not None and son_dt >= aday:
            aday = datetime.combine(aday_tarih + timedelta(days=7), saat_obj)
        elif fark == 0 and ref < aday and (son_dt is None or son_dt < aday):
            return aday
        return aday

    return None


def vadesi_geldi_mi(kayit: dict[str, Any], simdi: datetime | None = None) -> bool:
    """Etkin bir görevin şu an çalıştırılması gerekip gerekmediğini döndürür (saf fonksiyon)."""
    if not kayit.get("etkin", True):
        return False
    ref = simdi or datetime.now()
    saat_obj = _saat_coz(str(kayit.get("saat") or ""))
    if saat_obj is None:
        return False
    siklik = kayit.get("siklik")
    son_str = kayit.get("son_calisma")
    son_dt: datetime | None = None
    if isinstance(son_str, str) and son_str:
        try:
            son_dt = datetime.fromisoformat(son_str)
        except ValueError:
            son_dt = None

    if siklik == "bir_kez":
        t_obj = _tarih_coz(str(kayit.get("tarih") or ""))
        if t_obj is None:
            return False
        hedef = datetime.combine(t_obj, saat_obj)
        return ref >= hedef and (son_dt is None or son_dt < hedef)

    if siklik == "gunluk":
        hedef = datetime.combine(ref.date(), saat_obj)
        return ref >= hedef and (son_dt is None or son_dt < hedef)

    if siklik == "haftalik":
        hedef_gun = int(kayit.get("gun", 0))
        if ref.weekday() != hedef_gun:
            return False
        hedef = datetime.combine(ref.date(), saat_obj)
        return ref >= hedef and (son_dt is None or son_dt < hedef)

    return False


def listele(simdi: datetime | None = None) -> list[dict[str, Any]]:
    """Kayıtlı zamanlanmış görevleri `sonraki_zaman` bilgisiyle döndürür."""
    with _KILIT:
        kayitlar = _oku_ham()
    sonuc: list[dict[str, Any]] = []
    for k in kayitlar:
        kopya = dict(k)
        sonraki = sonraki_calisma_zamani(kopya, simdi=simdi)
        kopya["sonraki_zaman"] = sonraki.strftime("%Y-%m-%d %H:%M") if sonraki else None
        sonuc.append(kopya)
    return sonuc


def kaydet(
    ad: str,
    gorev: str,
    siklik: str = "gunluk",
    saat: str = "09:00",
    mod: str = "dengeli",
    gun: int = 0,
    tarih: str = "",
    etkin: bool = True,
    gorev_id: str = "",
    simdi: datetime | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Zamanlanmış görevi doğrular ve atomik olarak kaydeder. `(kayit, hata)` döner."""
    temiz_ad = (ad or "").strip()
    if not temiz_ad:
        return None, t("Görev başlığı boş olamaz.")
    if len(temiz_ad) > 60:
        return None, t("Görev başlığı en fazla 60 karakter olabilir.")

    temiz_gorev = (gorev or "").strip()
    if not temiz_gorev:
        return None, t("Görev metni boş olamaz.")
    if len(temiz_gorev) > 4000:
        return None, t("Görev metni en fazla 4000 karakter olabilir.")

    temiz_siklik = (siklik or "").strip()
    if temiz_siklik not in SIKLIKLAR:
        return None, t("Geçersiz sıklık: '{siklik}'.", siklik=temiz_siklik)

    temiz_saat = (saat or "").strip()
    saat_obj = _saat_coz(temiz_saat)
    if saat_obj is None:
        return None, t("Saat biçimi 'SS:DD' (00:00 - 23:59) olmalıdır.")

    temiz_mod = (mod or "dengeli").strip()
    if temiz_mod not in MODLAR:
        return None, t("Geçersiz efor modu: '{mod}'.", mod=temiz_mod)

    try:
        gun_int = int(gun)
    except (TypeError, ValueError):
        return None, t("Haftanın günü 0 (Pazartesi) ile 6 (Pazar) arasında olmalıdır.")
    if isinstance(gun, bool) or not (0 <= gun_int <= 6):
        return None, t("Haftanın günü 0 (Pazartesi) ile 6 (Pazar) arasında olmalıdır.")

    temiz_tarih = (tarih or "").strip()
    if temiz_siklik == "bir_kez":
        if _tarih_coz(temiz_tarih) is None:
            return None, t("Tarih biçimi 'YYYY-AA-GG' olmalıdır.")
    else:
        temiz_tarih = ""

    ref = simdi or datetime.now()
    with _KILIT:
        mevcut = _oku_ham()
        hedef_id = (gorev_id or "").strip() or f"zg_{uuid.uuid4().hex[:8]}"
        eski = next((x for x in mevcut if x["id"] == hedef_id), None)

        # Yeni oluşturulan günlük/haftalık görevin bugünkü saati zaten geçmişse,
        # kaydedilir kaydedilmez anında tetiklenmemesi için son_calisma bugüne işaretlenir.
        varsayilan_son = eski["son_calisma"] if eski else None
        if eski is None and temiz_siklik in ("gunluk", "haftalik"):
            bugun_hedef = datetime.combine(ref.date(), saat_obj)
            if ref >= bugun_hedef:
                if temiz_siklik == "gunluk" or ref.weekday() == gun_int:
                    varsayilan_son = ref.isoformat(timespec="seconds")

        yeni_kayit: dict[str, Any] = {
            "id": hedef_id,
            "ad": temiz_ad,
            "gorev": temiz_gorev,
            "siklik": temiz_siklik,
            "saat": temiz_saat,
            "gun": gun_int,
            "tarih": temiz_tarih,
            "mod": temiz_mod,
            "etkin": bool(etkin),
            "son_calisma": varsayilan_son,
            "calisma_sayisi": eski["calisma_sayisi"] if eski else 0,
        }

        if eski is not None:
            for i, x in enumerate(mevcut):
                if x["id"] == hedef_id:
                    mevcut[i] = yeni_kayit
                    break
        else:
            mevcut.append(yeni_kayit)

        try:
            _atomik_yaz(YOL, mevcut)
        except OSError as e:
            return None, t("Zamanlanmış görevler kaydedilemedi: {hata}", hata=e)

    sonraki = sonraki_calisma_zamani(yeni_kayit, simdi=ref)
    sonuc = dict(yeni_kayit)
    sonuc["sonraki_zaman"] = sonraki.strftime("%Y-%m-%d %H:%M") if sonraki else None
    return sonuc, None


def sil(gorev_id: str) -> str | None:
    """Belirtilen kimlikli zamanlanmış görevi siler."""
    hedef = (gorev_id or "").strip()
    if not hedef:
        return t("Görev bulunamadı: '{id}'.", id=hedef)
    with _KILIT:
        mevcut = _oku_ham()
        yeni = [x for x in mevcut if x["id"] != hedef]
        if len(yeni) == len(mevcut):
            return t("Görev bulunamadı: '{id}'.", id=hedef)
        try:
            _atomik_yaz(YOL, yeni)
        except OSError as e:
            return t("Zamanlanmış görevler kaydedilemedi: {hata}", hata=e)
    return None


def durum_degistir(gorev_id: str, etkin: bool) -> str | None:
    """Görevin etkin/duraklatılmış durumunu günceller."""
    hedef = (gorev_id or "").strip()
    with _KILIT:
        mevcut = _oku_ham()
        bulundu = False
        for x in mevcut:
            if x["id"] == hedef:
                x["etkin"] = bool(etkin)
                bulundu = True
                break
        if not bulundu:
            return t("Görev bulunamadı: '{id}'.", id=hedef)
        try:
            _atomik_yaz(YOL, mevcut)
        except OSError as e:
            return t("Zamanlanmış görevler kaydedilemedi: {hata}", hata=e)
    return None


def _isaretle_basladi(gorev_id: str, simdi: datetime | None = None) -> dict[str, Any] | None:
    ref = simdi or datetime.now()
    with _KILIT:
        mevcut = _oku_ham()
        secilen: dict[str, Any] | None = None
        for x in mevcut:
            if x["id"] == gorev_id:
                x["son_calisma"] = ref.isoformat(timespec="seconds")
                x["calisma_sayisi"] = int(x.get("calisma_sayisi") or 0) + 1
                if x.get("siklik") == "bir_kez":
                    x["etkin"] = False
                secilen = dict(x)
                break
        if secilen is not None:
            try:
                _atomik_yaz(YOL, mevcut)
            except OSError:
                pass
        return secilen


def tetikle(kopru: Any, gorev_id: str, simdi: datetime | None = None) -> dict[str, Any]:
    """Zamanlanmış görevi standart onay kapısı ve kota kurallarıyla (`kopru.gorev_baslat`) başlatır."""
    if kopru.calisiyor():
        return {"ok": False, "hata": t("Önce çalışan görevi durdur.")}
    hedef = (gorev_id or "").strip()
    with _KILIT:
        mevcut = _oku_ham()
        kayit = next((dict(x) for x in mevcut if x["id"] == hedef), None)
    if kayit is None:
        return {"ok": False, "hata": t("Görev bulunamadı: '{id}'.", id=hedef)}

    gosterim = f"⏰ [{kayit['ad']}] {kayit['gorev']}"
    try:
        # Profil parametresi VERİLMEZ: görev normal onay kapısından (gate.py) ve
        # günlük/adım/çağrı/istek kotalarından (journal.kota_ayir) geçer.
        kopru.gorev_baslat(kayit["gorev"], mod=kayit["mod"], ekip=False, gosterim=gosterim)
    except RuntimeError as e:
        return {"ok": False, "hata": str(e)}

    guncel = _isaretle_basladi(hedef, simdi=simdi) or kayit
    return {"ok": True, "gorev": guncel}


def vadesi_geleni_tetikle(kopru: Any, simdi: datetime | None = None) -> dict[str, Any] | None:
    """Köprü boşta ise vadesi gelmiş ilk etkin görevi başlatır ve bilgisini döndürür."""
    if kopru.calisiyor():
        return None
    ref = simdi or datetime.now()
    with _KILIT:
        mevcut = _oku_ham()
    for kayit in mevcut:
        if vadesi_geldi_mi(kayit, simdi=ref):
            sonuc = tetikle(kopru, kayit["id"], simdi=ref)
            if sonuc.get("ok"):
                return sonuc.get("gorev")
            break
    return None
