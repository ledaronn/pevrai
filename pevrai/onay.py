"""onay.py — Onay kartı hazırlığı, etki hesaplama ve fark üretimi.

Döngü ve arayüzden bağımsız onay ve güvenlik mantığı.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from pevrai.ceviri import t
from pevrai import journal
from pevrai.baglam import B
from pevrai.gate_kurallar import (
    masaustu_yikici_mi,
    terminal_komut_anahtari,
    terminal_yikici_mi,
)
from pevrai.olaylar import OnayIstegi, Oturum, onay_iste
from pevrai.araclar.ortak import args_gizle as _args_gizle

# Toplu onaya ASLA girmeyen riskler.
TOPLU_ONAY_YASAK = {"DESTRUCTIVE"}

# Risk seviyesinden BAĞIMSIZ, ada göre toplu onaydan çıkarılan araçlar.
# open_file: program/dosya başlatma her zaman tek tek sorulur, toplu onaya girmez.
TOPLU_ONAY_YASAK_ARAC = {"converter.convert", "open_file"}

# Fark gösteriminde azami satır (ARAYUZ.md 4.5).
FARK_AZAMI_SATIR = 200


def _toplu_sunulabilir_mi(arac: str, risk: str, yikici: bool) -> bool:
    """Bu araç için "Tümü" düğmesi RENDER EDİLEBİLİR mi? Saf karar.

    Faz 7 Aşama 1: kural eskiden _onay_gerekli_mi içinde satır arasındaydı
    ve MCP araçlarını ADA göre dışlıyordu (TOPLU_ONAY_YASAK_ARAC = {"converter.convert"}).
    Gerekçesi ise ada değil SINIFA aitti: "MCP sunucusu tarafında üretilen
    dosya journal'a hiç girmiyor, yedeği/geri alması yok." Bu, converter.convert'e
    özgü bir durum değil — BÜTÜN MCP yazma araçları için geçerli.

    MCP aracı ayrımı ada bakarak yapılır ("sunucu.arac"): köprü araçları bu
    biçimde kaydeder, yerel araçların adında nokta yoktur.
    """
    if yikici or risk in TOPLU_ONAY_YASAK:
        return False
    if arac in TOPLU_ONAY_YASAK_ARAC:
        return False
    return "." not in arac        # MCP araçları toplu onaya HİÇ girmez


def _yikici_yazma_mi(arac: str, args: dict, yol: Path | None) -> bool:
    """İçeriği yok eden write_file, yıkıcı terminal komutu ve kritik pencere eylemleri
    toplu onayı atlar, her seferinde ayrı sorulur."""
    if arac == "terminal_run":
        return terminal_yikici_mi(str(args.get("command", "")))
    if arac in ("window_click", "window_type", "window_key"):
        return masaustu_yikici_mi(arac, args)
    if arac != "write_file":
        return False
    hedef = yol or Path(args.get("path", ""))
    if not hedef.exists():
        return False
    yeni = len(str(args.get("content", "")).encode("utf-8"))
    eski = hedef.stat().st_size
    return yeni == 0 or (eski > 0 and yeni < eski * 0.2)


def _edit_eslesme(hedef: Path, eski_metin: str) -> int:
    """edit_file: old_text dosyada kac kez geciyor (onay karti icin on izleme)."""
    try:
        return hedef.read_text(encoding="utf-8").count(eski_metin) if eski_metin else 0
    except (OSError, UnicodeDecodeError):
        return 0


def _etki_cumlesi(arac: str, args: dict, yol: Path | None) -> str:
    """Onay kartındaki tek cümlelik etki. Araca özgü (ARAYUZ.md 4.4)."""
    hedef = yol or Path(args.get("path", ""))
    if arac == "write_file":
        yeni_bayt = len(str(args.get("content", "")).encode("utf-8"))
        if not hedef.exists():
            return t("yeni dosya oluşturulacak ({bayt} bayt)", bayt=yeni_bayt)
        try:
            eski_bayt = hedef.stat().st_size
        except OSError:
            return t("ÜZERİNE YAZILACAK ({bayt} bayt, yedek alınır)", bayt=yeni_bayt)
        return t("ÜZERİNE YAZILACAK: {eski} bayt -> {yeni} bayt ({fark:+d}, yedek alınır)",
                 eski=eski_bayt, yeni=yeni_bayt, fark=yeni_bayt - eski_bayt)
    if arac == "edit_file":
        eski_p, yeni_p = str(args.get("old_text", "")), str(args.get("new_text", ""))
        sayi = _edit_eslesme(hedef, eski_p)
        if sayi == 0:
            return t("düzenleme UYGULANMAYACAK: old_text bulunamadı (araç hata döndürecek)")
        if sayi != 1:
            return t("düzenleme UYGULANMAYACAK: old_text {sayi} kez geçiyor (araç hata döndürecek)", sayi=sayi)
        return t("yerinde düzenleme: {eski_satir} satır -> {yeni_satir} satır, "
                 "{eski_kr} -> {yeni_kr} karakter (yedek alınır)",
                 eski_satir=eski_p.count("\n") + 1,
                 yeni_satir=(yeni_p.count("\n") + 1) if yeni_p else 0,
                 eski_kr=len(eski_p), yeni_kr=len(yeni_p))
    if arac == "mkdir":
        return t("yeni klasör oluşturulacak (boşken geri alınabilir)")
    if arac == "open_file":
        from pevrai.araclar import acma as _acma
        if hedef.exists():
            tur, aciklama, hata = _acma.hedef_cozumle(hedef, B.politika)
            return hata if hata else aciklama
        return t("'{ad}' açma klasöründe yok (araç hata döndürecek)", ad=hedef.name)
    if arac == "move":
        return t("dosya KAYNAKTAN KAYBOLACAK -> {hedef}", hedef=args.get("dst", "?"))
    if arac == "rename":
        return t("yeni ad: {ad}", ad=args.get("new_name", "?"))
    if arac == "trash":
        return t("çöp klasörüne taşınacak (kalıcı silinmez, geri alınabilir)")
    if arac == "browser_open":
        return t("açılacak adres: {adres}", adres=args.get("url", "?"))
    if arac == "browser_download":
        return t("dosya internetten inecek ({klasor} klasörüne)", klasor=journal.INEN)
    if arac == "browser_click":
        return t("'{ad}' ögesine tıklanacak", ad=args.get("name", "?"))
    if arac == "browser_fill":
        return t("'{ad}' alanına yazılacak", ad=args.get("name", "?"))
    if arac == "terminal_run":
        komut = str(args.get("command", "?")).strip()
        klasor = str(yol) if yol else str(args.get("cwd", "?"))
        if terminal_yikici_mi(komut):
            return t("YIKICI KOMUT çalıştırılacak: {komut} (klasör: {klasor})",
                     komut=komut[:120], klasor=klasor)
        return t("komut çalıştırılacak: {komut} (klasör: {klasor})",
                 komut=komut[:120], klasor=klasor)
    if arac == "window_click":
        pencere = str(args.get("window", "?"))
        oge = str(args.get("name") or args.get("automation_id")
                  or f"({args.get('x', '?')}, {args.get('y', '?')})")
        return t("'{pencere}' penceresinde '{oge}' ögesine tıklanacak",
                 pencere=pencere, oge=oge)
    if arac == "window_type":
        pencere = str(args.get("window", "?"))
        alan = str(args.get("name") or args.get("automation_id") or t("odaklı alan"))
        if bool(args.get("submit", False)):
            return t("'{pencere}' penceresinde '{alan}' alanına yazılıp Enter basılacak",
                     pencere=pencere, alan=alan)
        return t("'{pencere}' penceresinde '{alan}' alanına metin yazılacak",
                 pencere=pencere, alan=alan)
    if arac == "window_key":
        pencere = str(args.get("window", "?"))
        tus = str(args.get("key") or args.get("keys") or "?")
        return t("'{pencere}' penceresine '{tus}' tuşu gönderilecek",
                 pencere=pencere, tus=tus)
    if arac.startswith("converter."):
        kaynak = Path(str(args.get("src", "?"))).name
        klasor = str(args.get("dst_dir", "?"))
        bicim = str(args.get("target_format", "")).lstrip(".").lower()
        if not bicim.isalnum():
            return t("{kaynak} dönüştürülecek -> {klasor}", kaynak=kaynak, klasor=klasor)
        cikti = Path(klasor) / f"{Path(str(args.get('src', ''))).stem}.{bicim}"
        if cikti.exists():
            if getattr(B.kopru, "geri_alinabilir", lambda _: False)(arac):
                return t("{kaynak} -> {cikti} ({klasor}) — MEVCUT DOSYA YEDEKLENECEK, geri alınabilir",
                         kaynak=kaynak, cikti=cikti.name, klasor=klasor)
            return t("{kaynak} -> {cikti} ({klasor}) — MEVCUT DOSYANIN ÜSTÜNE YAZILACAK, geri alınamaz",
                     kaynak=kaynak, cikti=cikti.name, klasor=klasor)
        return f"{kaynak} -> {cikti.name} ({klasor})"
    return t("{arac} çalıştırılacak", arac=arac)


def _fark_uret(arac: str, args: dict, yol: Path | None) -> str | None:
    """Üzerine yazmada satır bazlı fark. Onayı anlamlı kılan tek şey (ARAYUZ.md 4.5)."""
    if arac not in ("write_file", "edit_file") or yol is None or not yol.exists() or yol.is_dir():
        return None
    try:
        eski_metin = yol.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    eski = eski_metin.splitlines()

    if arac == "edit_file":
        e, y = str(args.get("old_text", "")), str(args.get("new_text", ""))
        if not e or eski_metin.count(e) != 1:
            return None
        yeni = eski_metin.replace(e, y, 1).splitlines()
    else:
        yeni = str(args.get("content", "")).splitlines()
    satirlar = list(difflib.unified_diff(eski, yeni, t("mevcut"), t("yeni"), lineterm="", n=2))
    if not satirlar:
        return t("(içerik aynı)")
    if len(satirlar) > FARK_AZAMI_SATIR:
        kalan = len(satirlar) - FARK_AZAMI_SATIR
        satirlar = satirlar[:FARK_AZAMI_SATIR] + [t("... [fark kırpıldı, {satir} satır daha var]", satir=kalan)]
    return "\n".join(satirlar)


def _onay_gerekli_mi(oturum: Oturum, arac: str, args: dict,
                     risk: str, yol: Path | None) -> bool:
    """Onay isteğini kurar; kararı olaylar.onay_iste verir."""
    yikici = _yikici_yazma_mi(arac, args, yol)

    # Masaüstü pencere kontrolü: aynı oturumda kullanıcı bu açık pencereye
    # bir kez izin verdiyse, yıkıcı olmayan (Sil/Gönder/Kaydet/Kapat/submit dışındaki)
    # standart tıklama ve yazma adımları tekrar onay istemez.
    if arac in ("window_click", "window_type", "window_key"):
        pencere_adi = str(args.get("window", "")).strip()
        if not yikici and pencere_adi and oturum.pencere_onayli(pencere_adi):
            return True

    # Terminal komutu: oturumda bu komut ön-eki onaylandıysa ve yıkıcı değilse geçer.
    if arac == "terminal_run":
        komut_anahtari = terminal_komut_anahtari(str(args.get("command", "")))
        if not yikici and komut_anahtari and oturum.komut_onayli(komut_anahtari):
            return True

    istek = OnayIstegi(
        arac=arac,
        args=_args_gizle(args),
        risk=risk,
        etki=_etki_cumlesi(arac, args, yol),
        yikici=yikici,
        toplu_sunulabilir=_toplu_sunulabilir_mi(arac, risk, yikici),
        fark=_fark_uret(arac, args, yol),
    )
    if arac in B.kopru.araclar and risk not in {"READ"}:
        from dataclasses import replace
        supported = getattr(B.kopru, "geri_alinabilir", lambda _: False)(arac)
        note = t("Bu aracın dosya çıktıları yedeklenir ve geri alınabilir.") if supported else t("Bu dış aracın işlemleri Pevrai'nın geri alma kapsamına girmez.")
        istek = replace(istek, etki=istek.etki + " " + note)
    onaylandi = onay_iste(oturum, istek)
    if onaylandi:
        if arac in ("window_click", "window_type", "window_key"):
            pencere_adi = str(args.get("window", "")).strip()
            if pencere_adi:
                oturum.pencere_onayla(pencere_adi)
        elif arac == "terminal_run" and not yikici and oturum.toplu_onayli("terminal_run"):
            komut_anahtari = terminal_komut_anahtari(str(args.get("command", "")))
            if komut_anahtari:
                oturum.komut_onayla(komut_anahtari)
    return onaylandi

