"""terminal_masaustu_testi.py — Terminal erişimi (terminal_run) ve masaüstü
pencere kontrolü (window_*) için kapı, onay, fark ve çalışma zamanı testleri.

Çalıştırma:
    python tests/terminal_masaustu_testi.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from pevrai.baglam import B
from pevrai.gate import ALLOW, ASK, DENY, Politika
from pevrai.gate_kurallar import (
    masaustu_yasakli_mi,
    masaustu_yikici_mi,
    terminal_komut_anahtari,
    terminal_yikici_mi,
)
from pevrai.olaylar import OlayTipi, OnayCevabi, Oturum
from pevrai.onay import TOPLU_ONAY_YASAK_ARAC, _onay_gerekli_mi, _toplu_sunulabilir_mi, _yikici_yazma_mi
from pevrai.araclar import masaustu, terminal


basarili = 0
basarisiz = 0


def kontrol(kosul: bool, ad: str, ayrinti: str = "") -> None:
    global basarili, basarisiz
    if kosul:
        basarili += 1
        print(f"  GECTI  {ad}")
    else:
        basarisiz += 1
        ek = f" — {ayrinti}" if ayrinti else ""
        print(f"  KALDI  {ad}{ek}")


def _test_politikasi(okuma_kok: Path, yazma_kok: Path) -> Politika:
    p = Politika.__new__(Politika)
    p.okuma = [okuma_kok.resolve(), yazma_kok.resolve()]
    p.yazma = [yazma_kok.resolve()]
    p.yasak = [".env", "*.env", "*.key", "*secret*", "*password*"]
    p.araclar = {
        "terminal_run": "WRITE",
        "window_list": "READ",
        "window_read": "READ",
        "window_click": "WRITE_HAFIF",
        "window_type": "WRITE_HAFIF",
        "window_key": "WRITE_HAFIF",
        "open_file": "EXEC",
    }
    p.arac_yollari = {}
    p.kaldirilan_paketler = []
    p.mcp = {}
    p.acma_klasoru = None
    p.acma_red_nedeni = None
    p.izinli_alanlar = []
    p.yerel_kokler = []
    p.uzantilar = []
    p.eylemler = {}
    p.site_eylemleri = {}
    p.modlar = {}
    p.varsayilan_mod = "dengeli"
    p.profiller = {}
    p.gunluk_tavan = {}
    p.persona_acik = False
    p.ajanlar = {}
    p.baglantilar = {}
    p.model_zinciri = []
    p.derin_tercih = ""
    return p


def test_terminal_kapi() -> None:
    print("\n1) Terminal izin kapısı (ALLOW / ASK / DENY ve yıkıcı komut ayrımı)")
    with tempfile.TemporaryDirectory() as tmp:
        kok = Path(tmp)
        okuma_dizin = kok / "okuma"
        yazma_dizin = kok / "yazma"
        dis_dizin = kok / "disari"
        okuma_dizin.mkdir()
        yazma_dizin.mkdir()
        dis_dizin.mkdir()

        pol = _test_politikasi(okuma_dizin, yazma_dizin)

        # 1. Güvenli salt okunur komutlar -> ALLOW (hem okuma hem yazma kökünde)
        for cmd in ("git status", "git diff --stat", "pytest -q", "dir", "echo merhaba", "python --version"):
            k = pol.karar("terminal_run", {"command": cmd, "cwd": str(okuma_dizin)})
            kontrol(k.sonuc == ALLOW, f"salt okunur ALLOW ({cmd})", f"sonuc={k.sonuc}, gerekce={k.gerekce}")

        # 2. Yazan / değiştiren komutlar -> yazma kökünde ASK, okuma kökünde DENY
        for cmd in ("python script.py", "pip install requests", "git commit -m test", "echo x > a.txt", "git status && dir"):
            k_yaz = pol.karar("terminal_run", {"command": cmd, "cwd": str(yazma_dizin)})
            k_oku = pol.karar("terminal_run", {"command": cmd, "cwd": str(okuma_dizin)})
            kontrol(k_yaz.sonuc == ASK, f"değiştiren komut yazma kökünde ASK ({cmd})", f"sonuc={k_yaz.sonuc}")
            kontrol(k_oku.sonuc == DENY, f"değiştiren komut okuma kökünde DENY ({cmd})", f"sonuc={k_oku.sonuc}")

        # 3. Yasaklı / felaket komutlar ve korumalı yollar -> her yerde DENY
        for etiket, cmd in (
            ("format C:", "format C:"),
            ("diskpart", "diskpart"),
            ("bcdedit", "bcdedit"),
            ("reg delete HKCU\\Test", "reg delete HKCU\\Test"),
            ("powershell -EncodedCommand", "powershell -EncodedCommand ZQBjAGgAbwA="),
            ("Invoke-Expression $x", "Invoke-Expression $x"),
            ("type .env", "type .env"),
            ("izinli kök dışı klasör", f"dir {dis_dizin}"),
            ("proje policy.toml koruması", f"type {KOK / 'policy.toml'}"),
        ):
            k = pol.karar("terminal_run", {"command": cmd, "cwd": str(yazma_dizin)})
            kontrol(k.sonuc == DENY, f"yasaklı komut DENY ({etiket})", f"sonuc={k.sonuc}")

        # 4. Yıkıcı komut tespiti (toplu onaya giremez)
        kontrol(terminal_yikici_mi("rm -rf build"), "rm -rf yıkıcıdır")
        kontrol(terminal_yikici_mi("del /f /q a.txt"), "del yıkıcıdır")
        kontrol(terminal_yikici_mi("Remove-Item foo.txt"), "Remove-Item yıkıcıdır")
        kontrol(terminal_yikici_mi("git reset --hard HEAD~1"), "git reset --hard yıkıcıdır")
        kontrol(terminal_yikici_mi("taskkill /F /PID 1234"), "taskkill yıkıcıdır")
        kontrol(not terminal_yikici_mi("pytest tests/"), "pytest yıkıcı değildir")
        kontrol(terminal_komut_anahtari("git commit -m 'msg'") == "git commit", "git alt komut anahtarı")


def test_terminal_calistirma_ve_fark() -> None:
    print("\n2) Terminal çalıştırma, gizli anahtar maskeleme ve dosya farkı (+/-) tespiti")
    with tempfile.TemporaryDirectory() as tmp:
        calisma = Path(tmp)
        (calisma / "mevcut.txt").write_text("satir1\nsatir2\n", encoding="utf-8")
        (calisma / "silinecek.txt").write_text("eski\n", encoding="utf-8")

        eski_pol = B.politika
        eski_oturum = getattr(B, "oturum", None)
        yayinlanan = []
        oturum = Oturum(onay_saglayici=lambda _: OnayCevabi.EVET, yayinla=lambda o: yayinlanan.append(o))
        B.politika = _test_politikasi(calisma, calisma)
        B.oturum = oturum
        os.environ["OPENAI_API_KEY"] = "sk-test-secret-key-99999"
        try:
            komut = (
                "Set-Content -Path 'yeni.txt' -Value 'merhaba' -Encoding utf8; "
                "Add-Content -Path 'mevcut.txt' -Value 'satir3' -Encoding utf8; "
                "Remove-Item -Path 'silinecek.txt'; "
                "Write-Output ('ANAHTAR=' + $env:OPENAI_API_KEY)"
            )
            sonuc = terminal.terminal_run(
                calisma,
                {"command": komut, "cwd": str(calisma), "timeout": 20},
            )
            kontrol(getattr(sonuc, "basarili", False) is True, "terminal_run başarılı döndü")
            kontrol("<untrusted_content" in str(sonuc), "çıktı <untrusted_content> içinde")
            kontrol("sk-test-secret-key-99999" not in str(sonuc), "gizli API anahtarı alt sürece sızmadı")
            kontrol(any(o.tip is OlayTipi.TERMINAL_CIKTI for o in yayinlanan), "canlı TERMINAL_CIKTI olayı yayınlandı")

            ek = getattr(sonuc, "ek", None) or {}
            term_bilgi = ek.get("terminal") or {}
            degisiklikler = {d["goreli"]: d for d in (term_bilgi.get("degisiklikler") or [])}
            kontrol("yeni.txt" in degisiklikler and degisiklikler["yeni.txt"]["tur"] == "eklendi",
                    "yeni oluşturulan dosya tespit edildi")
            kontrol("mevcut.txt" in degisiklikler and degisiklikler["mevcut.txt"]["tur"] == "duzenlendi",
                    "düzenlenen dosya ve farkı tespit edildi")
            kontrol("silinecek.txt" in degisiklikler and degisiklikler["silinecek.txt"]["tur"] == "silindi",
                    "silinen dosya tespit edildi")
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
            B.politika = eski_pol
            B.oturum = eski_oturum


def test_masaustu_kapi_ve_oturum_onayi() -> None:
    print("\n3) Masaüstü pencere kontrolü: açık pencere kuralı, kara liste ve oturum onayı")
    with tempfile.TemporaryDirectory() as tmp:
        kok = Path(tmp)
        pol = _test_politikasi(kok, kok)

        # 1. window_list ve normal window_read -> ALLOW
        kontrol(pol.karar("window_list", {}).sonuc == ALLOW, "window_list ALLOW")
        kontrol(pol.karar("window_read", {"window": "Not Defteri"}).sonuc == ALLOW, "window_read ALLOW")

        # 2. Güvenlik kara listesi -> DENY
        for yasak_pencere in ("Pevrai", "Windows PowerShell", "cmd.exe", "Görev Yöneticisi", "Task Manager", "Registry Editor", "Bitwarden"):
            kontrol(masaustu_yasakli_mi(yasak_pencere), f"kara liste tespiti ({yasak_pencere})")
            kontrol(pol.karar("window_read", {"window": yasak_pencere}).sonuc == DENY,
                    f"yasaklı pencere okuma DENY ({yasak_pencere})")
            kontrol(pol.karar("window_click", {"window": yasak_pencere, "name": "Tamam"}).sonuc == DENY,
                    f"yasaklı pencere tıklama DENY ({yasak_pencere})")

        # 3. Ödeme düğmeleri ve parola alanları -> DENY
        kontrol(pol.karar("window_click", {"window": "Uygulama", "name": "Satın Al"}).sonuc == DENY,
                "ödeme düğmesine tıklama DENY")
        kontrol(pol.karar("window_type", {"window": "Uygulama", "name": "Parola", "text": "deneme"}).sonuc == DENY,
                "parola alanına yazma DENY")

        # 4. Standart pencere etkileşimi: ilk seferde sorar, onaylanınca aynı pencerede tekrar sormaz;
        #    kritik eylemler (Sil/Kaydet/Alt+F4/submit=True) ise HER ZAMAN sorar.
        sorulanlar = []
        oturum = Oturum(onay_saglayici=lambda istek: (sorulanlar.append(istek.arac) or OnayCevabi.EVET))
        eski_pol, eski_kopru = B.politika, B.kopru
        B.politika = pol
        B.kopru = type("_BosKopru", (), {"araclar": {}})()
        try:
            onay1 = _onay_gerekli_mi(oturum, "window_click", {"window": "Not Defteri", "name": "Düzen"}, "WRITE_HAFIF", None)
            kontrol(onay1 is True and len(sorulanlar) == 1, "ilk pencere etkileşiminde onay soruldu")
            kontrol(oturum.pencere_onayli("Not Defteri"), "pencere oturumda onaylı işaretlendi")

            onay2 = _onay_gerekli_mi(oturum, "window_type", {"window": "Not Defteri", "text": "merhaba"}, "WRITE_HAFIF", None)
            kontrol(onay2 is True and len(sorulanlar) == 1, "aynı pencerede standart yazma tekrar onay sormadı")

            # Kritik eylem (Kaydet / Alt+F4 / submit=True) aynı pencerede bile tekrar onay sorar!
            kontrol(masaustu_yikici_mi("window_click", {"window": "Not Defteri", "name": "Kaydet"}), "Kaydet düğmesi yıkıcı/kritik")
            kontrol(masaustu_yikici_mi("window_key", {"window": "Not Defteri", "keys": "Alt+F4"}), "Alt+F4 yıkıcı/kritik")
            kontrol(masaustu_yikici_mi("window_type", {"window": "Not Defteri", "text": "x", "submit": True}), "submit=True yıkıcı/kritik")

            onay3 = _onay_gerekli_mi(oturum, "window_click", {"window": "Not Defteri", "name": "Kaydet"}, "WRITE_HAFIF", None)
            kontrol(onay3 is True and len(sorulanlar) == 2, "kritik düğme (Kaydet) onaylı pencerede bile tekrar sordu")

            # Başka bir açık pencereye geçince tekrar onay sorar
            onay4 = _onay_gerekli_mi(oturum, "window_click", {"window": "Hesap Makinesi", "name": "5"}, "WRITE_HAFIF", None)
            kontrol(onay4 is True and len(sorulanlar) == 3, "farklı pencereye geçince onay sordu")
        finally:
            B.politika = eski_pol
            B.kopru = eski_kopru

        # 5. Kapalı programı ASLA kendi kendine açmaz
        kapali_sonuc = masaustu.window_read(None, {"window": "KesinlikleAcikOlmayanProgram_987654"})
        kontrol(getattr(kapali_sonuc, "basarili", True) is False, "kapalı pencere hata döndürür (program başlatmaz)")
        kapali_metin = str(kapali_sonuc)
        kontrol(
            any(ibare in kapali_metin for ibare in ("AÇMAZ", "başlatamaz", "bulunamadı", "cannot launch", "No open window")),
            "kapalı pencere mesajı açıkça programı açmadığını belirtir",
        )

        # 6. open_file toplu onaya asla girmez (program açarken her zaman sorar)
        kontrol("open_file" in TOPLU_ONAY_YASAK_ARAC, "open_file TOPLU_ONAY_YASAK_ARAC içinde")
        kontrol(not _toplu_sunulabilir_mi("open_file", "EXEC", False), "open_file için 'Bu oturumda sorma' kapalı")


def test_arayuz_terminal_ve_akis() -> None:
    print("\n4) Arayüz terminal kartı ve akış (streaming) regresyon denetimi")
    app_js = (KOK / "pevrai" / "arayuz" / "app.js").read_text(encoding="utf-8")
    stil_css = (KOK / "pevrai" / "arayuz" / "stil.css").read_text(encoding="utf-8")
    kontrol("function kaydir()" in app_js, "app.js içinde kaydir() fonksiyonu tanımlı")
    kontrol("function terminalKarti(v)" in app_js, "app.js içinde terminalKarti(v) tanımlı")
    kontrol('case "arac_cagrildi": if (aktifAkis) akisKapat();' in app_js,
            "arac_cagrildi geldiğinde açık akış (aktifAkis) kapatılıyor")
    kontrol('case "onay_gerekli": if (aktifAkis) akisKapat();' in app_js,
            "onay_gerekli geldiğinde açık akış (aktifAkis) kapatılıyor")
    kontrol(".terminal-kart" in stil_css and ".terminal-cikti:empty::before" in stil_css,
            "stil.css içinde siyah terminal kartı ve bekleme durumu stilleri tanımlı")


if __name__ == "__main__":
    test_terminal_kapi()
    test_terminal_calistirma_ve_fark()
    test_masaustu_kapi_ve_oturum_onayi()
    test_arayuz_terminal_ve_akis()
    print(f"\nSonuc: {basarili} gecti, {basarisiz} kaldi")
    sys.exit(1 if basarisiz else 0)

