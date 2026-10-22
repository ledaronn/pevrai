"""araclar/terminal.py — Claude Code tarzi katmanli terminal araci (terminal_run).

Tasarim:
  1. Izin kapisi (gate_kurallar.terminal_karari):
     - Calisma dizini (cwd) izinli koklerin icinde olmalidir; verilmezse
       varsayilan calisma klasoru kullanilir.
     - Kendi kaynak koduna (PAKET), policy.toml'a, .vekil'e, kara liste
       kaliplarina (.env, *.pem, id_rsa...) ve yikici sistem komutlarina
       (format, diskpart, bcdedit, regedit...) erisim KESINLIKLE DENY.
     - Zincirleme/yonlendirme icermeyen salt-okuma komutlari (git status/diff/log,
       dir, ls, echo, pytest, python --version...) ALLOW.
     - Degistiren, paket kuran, betik calistiran ya da kabuk zinciri (|, >, &&, ;)
       iceren komutlar ASK (yalnizca yazma koklerinde).
  2. Degisiklik takibi ve canli cikti:
     - Komut calismadan once ve sonra calisma dizinindeki dosyalarin anlik
       goruntusu alinir; olusturulan, degistirilen ve silinen dosyalar ile
       satir bazli farklar (+/-) tespit edilerek arayuzdeki siyah terminal
       kartinda gosterilir.
     - Cikti satirlari canli olarak OlayTipi.TERMINAL_CIKTI ile arayuze akar.
     - Ortam degiskenlerinden API anahtarlari ve gizli belirtecler temizlenir.
"""
from __future__ import annotations

import difflib
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from pevrai.araclar.kayit import arac
from pevrai.araclar.ortak import MAX_OUTPUT, hassas_maskele
from pevrai.baglam import B
from pevrai.ceviri import t
from pevrai.olaylar import Olay, OlayTipi
from pevrai.sonuc import AracSonucu, hata as sonuc_hatasi

VARSAYILAN_ZAMAN_ASIMI = 30
AZAMI_ZAMAN_ASIMI = 120
ANLIK_AZAMI_DOSYA = 1200
ANLIK_AZAMI_BOYUT = 256 * 1024
ATLANAN_KLASORLER = frozenset({
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build", ".vekil",
})
GIZLI_ORTAM_KALIBI = re.compile(
    r"(API_KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|PRIVATE_KEY|^PEVRAI_)", re.I
)


def _temiz_ortam() -> dict[str, str]:
    """Alt surece gidecek ortam degiskenlerinden API anahtarlarini ayiklar."""
    ortam = {}
    for k, v in os.environ.items():
        if GIZLI_ORTAM_KALIBI.search(k):
            continue
        ortam[k] = v
    ortam["PYTHONIOENCODING"] = "utf-8"
    ortam["PYTHONUTF8"] = "1"
    return ortam


def _sarmala(metin: str, kaynak: str = "terminal_run") -> str:
    temiz = re.sub(r"</\s*untrusted_content\s*>", "[/untrusted_content]", metin, flags=re.I)
    return f'<untrusted_content kaynak="{kaynak}">\n{temiz}\n</untrusted_content>'


def _klasor_anlik_goruntu(kok: Path) -> dict[str, tuple[int, int, str | None]]:
    """Klasordeki dosyalarin (mtime_ns, boyut, metin_icerigi) haritasini cikarir."""
    goruntu: dict[str, tuple[int, int, str | None]] = {}
    if not kok.exists() or not kok.is_dir():
        return goruntu
    sayac = 0
    try:
        for taban, alt_klasorler, dosyalar in os.walk(kok):
            alt_klasorler[:] = [d for d in alt_klasorler if d not in ATLANAN_KLASORLER]
            for ad in dosyalar:
                sayac += 1
                if sayac > ANLIK_AZAMI_DOSYA:
                    return goruntu
                tam = Path(taban) / ad
                if B.politika and B.politika._yasakli_mi(tam):
                    continue
                try:
                    st = tam.stat()
                    goreli = tam.relative_to(kok).as_posix()
                    icerik: str | None = None
                    if st.st_size <= ANLIK_AZAMI_BOYUT:
                        try:
                            ham = tam.read_bytes()
                            if b"\x00" not in ham[:4096]:
                                icerik = ham.decode("utf-8", errors="replace")
                        except OSError:
                            icerik = None
                    goruntu[goreli] = (st.st_mtime_ns, st.st_size, icerik)
                except OSError:
                    continue
    except OSError:
        pass
    return goruntu


def _degisiklikleri_hesapla(
    onceki: dict[str, tuple[int, int, str | None]],
    sonraki: dict[str, tuple[int, int, str | None]],
    kok: Path | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Iki anlik goruntu arasindaki dosya degisikliklerini ve birlesik farki (diff) uretir."""
    degisiklikler: list[dict[str, Any]] = []
    fark_parcalari: list[str] = []

    tum_yollar = sorted(set(onceki) | set(sonraki))
    for yol in tum_yollar:
        tam_yol = str((kok / yol).resolve()) if kok is not None else yol
        eski = onceki.get(yol)
        yeni = sonraki.get(yol)
        if eski is None and yeni is not None:
            yeni_metin = yeni[2]
            satirlar = yeni_metin.splitlines() if yeni_metin is not None else []
            eklenen = len(satirlar)
            dosya_fark_satirlari: list[str] = []
            if satirlar:
                dosya_fark_satirlari.append(f"--- /dev/null\n+++ b/{yol}")
                for s in satirlar[:40]:
                    dosya_fark_satirlari.append(f"+{s}")
                if len(satirlar) > 40:
                    dosya_fark_satirlari.append(f"... (+{len(satirlar) - 40} satır daha)")
                if len(fark_parcalari) < 120:
                    fark_parcalari.extend(dosya_fark_satirlari)
            degisiklikler.append({
                "yol": tam_yol,
                "goreli": yol,
                "durum": "eklendi",
                "tur": "eklendi",
                "eklenen": eklenen,
                "silinen": 0,
                "arti": eklenen,
                "eksi": 0,
                "fark": "\n".join(dosya_fark_satirlari),
            })
        elif eski is not None and yeni is None:
            eski_metin = eski[2]
            satirlar = eski_metin.splitlines() if eski_metin is not None else []
            silinen = len(satirlar)
            dosya_fark_satirlari = [f"--- a/{yol}\n+++ /dev/null"]
            for s in satirlar[:30]:
                dosya_fark_satirlari.append(f"-{s}")
            if len(fark_parcalari) < 120:
                fark_parcalari.extend(dosya_fark_satirlari)
            degisiklikler.append({
                "yol": tam_yol,
                "goreli": yol,
                "durum": "silindi",
                "tur": "silindi",
                "eklenen": 0,
                "silinen": silinen,
                "arti": 0,
                "eksi": silinen,
                "fark": "\n".join(dosya_fark_satirlari),
            })
        elif eski is not None and yeni is not None:
            if eski[0] == yeni[0] and eski[1] == yeni[1]:
                continue
            eski_metin, yeni_metin = eski[2], yeni[2]
            if eski_metin is not None and yeni_metin is not None and eski_metin == yeni_metin:
                continue
            eklenen = 0
            silinen = 0
            dosya_fark_satirlari = []
            if eski_metin is not None and yeni_metin is not None:
                diff = list(difflib.unified_diff(
                    eski_metin.splitlines(),
                    yeni_metin.splitlines(),
                    fromfile=f"a/{yol}",
                    tofile=f"b/{yol}",
                    lineterm="",
                    n=2,
                ))
                for d_satir in diff:
                    if d_satir.startswith("+") and not d_satir.startswith("+++"):
                        eklenen += 1
                    elif d_satir.startswith("-") and not d_satir.startswith("---"):
                        silinen += 1
                dosya_fark_satirlari = diff[:60]
                if diff and len(fark_parcalari) < 150:
                    fark_parcalari.extend(dosya_fark_satirlari)
            degisiklikler.append({
                "yol": tam_yol,
                "goreli": yol,
                "durum": "duzenlendi",
                "tur": "duzenlendi",
                "eklenen": eklenen,
                "silinen": silinen,
                "arti": eklenen,
                "eksi": silinen,
                "fark": "\n".join(dosya_fark_satirlari),
            })

    fark_metni = "\n".join(fark_parcalari[:180])
    return degisiklikler, fark_metni


def _sureci_sonlandir(proc: subprocess.Popen) -> None:
    """Windows'ta alt surec agacini (taskkill /F /T) temizce sonlandirir."""
    try:
        if proc.poll() is not None:
            return
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


@arac(
    ad="terminal_run",
    paket="terminal",
    risk="WRITE",
    baslik="Terminal komutu çalıştırma",
    aciklama="İzinli çalışma klasöründe terminal komutu çalıştırır; güvenli okuma komutları doğrudan, değiştiren komutlar onayla çalışır.",
    modele=(
        "İzinli klasörde bir terminal komutu (PowerShell) çalıştırır ve çıktısını (stdout/stderr), "
        "çıkış kodunu ve değiştirdiği dosyaları döndürür. Git durumu/farkı, test koşma (pytest), "
        "dizin inceleme gibi güvenli okuma komutları doğrudan çalışır; dosya değiştiren, paket "
        "kuran, betik çalıştıran veya kabuk zinciri (|, >, &&, ;) içeren komutlar kullanıcı onayı "
        "ister. Çıktı <untrusted_content> içindedir."
    ),
    sema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Çalıştırılacak terminal komutu (örn. 'git status', 'pytest', 'python main.py').",
            },
            "cwd": {
                "type": "string",
                "description": "İsteğe bağlı çalışma klasörü (tam yol veya çalışma klasörüne göre göreli). Boş bırakılırsa varsayılan çalışma klasörü kullanılır.",
            },
            "timeout": {
                "type": "integer",
                "description": "Zaman aşımı (saniye, varsayılan 30, en fazla 120).",
            },
        },
        "required": ["command"],
    },
)
def terminal_run(yol: Path | None, args: dict) -> str:
    komut = str((args or {}).get("command", "")).strip()
    if not komut:
        return sonuc_hatasi(t("Çalıştırılacak komut boş olamaz."))

    # Kapidan cozulmus yol gelmediyse (dogrudan test cagrisi) politikadan coz
    calisma_dizin = yol
    if calisma_dizin is None and B.politika is not None:
        from pevrai.gate_kurallar import DENY, terminal_karari
        k = terminal_karari(
            komut,
            str((args or {}).get("cwd", "")),
            B.politika.okuma,
            B.politika.yazma,
            B.politika.yasak,
            B.politika._proje_koku,
            varsayilan_cwd=B.politika.calisma,
        )
        if k.sonuc == DENY:
            return sonuc_hatasi(t("İzin reddedildi: {gerekce}", gerekce=k.gerekce))
        calisma_dizin = k.yol

    if calisma_dizin is None:
        return sonuc_hatasi(t("Terminal için geçerli bir çalışma klasörü bulunamadı."))

    if not calisma_dizin.exists():
        return sonuc_hatasi(t("Çalışma klasörü bulunamadı: '{yol}'", yol=calisma_dizin))
    if not calisma_dizin.is_dir():
        return sonuc_hatasi(t("'{yol}' bir klasör değil.", yol=calisma_dizin))

    try:
        zaman_asimi = int((args or {}).get("timeout") or VARSAYILAN_ZAMAN_ASIMI)
    except (TypeError, ValueError):
        zaman_asimi = VARSAYILAN_ZAMAN_ASIMI
    zaman_asimi = max(1, min(zaman_asimi, AZAMI_ZAMAN_ASIMI))

    onceki_goruntu = _klasor_anlik_goruntu(calisma_dizin)

    if sys.platform == "win32":
        utf8_on_ek = (
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "$OutputEncoding = [System.Text.Encoding]::UTF8; "
        )
        tam_komut = ["powershell", "-NoProfile", "-NonInteractive", "-Command", utf8_on_ek + komut]
    else:
        tam_komut = ["sh", "-c", komut]

    baslangic = time.monotonic()
    satirlar: list[str] = []
    zaman_asimi_oldu = False
    durduruldu = False

    try:
        proc = subprocess.Popen(
            tam_komut,
            cwd=str(calisma_dizin),
            env=_temiz_ortam(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as e:
        return sonuc_hatasi(t("Komut başlatılamadı: {hata}", hata=e))

    oturum = getattr(B, "oturum", None)

    def _okuyucu() -> None:
        assert proc.stdout is not None
        try:
            for satir in iter(proc.stdout.readline, ""):
                temiz_satir = hassas_maskele(satir)
                satirlar.append(temiz_satir)
                if oturum is not None:
                    try:
                        oturum.yayinla(Olay(OlayTipi.TERMINAL_CIKTI, {
                            "komut": komut,
                            "cwd": str(calisma_dizin),
                            "parca": temiz_satir,
                            "metin": temiz_satir.rstrip("\r\n"),
                        }))
                    except Exception:
                        pass
        except Exception:
            pass

    okuma_thread = threading.Thread(target=_okuyucu, daemon=True)
    okuma_thread.start()

    while proc.poll() is None:
        if oturum is not None and oturum.durdur_bayragi.is_set():
            durduruldu = True
            _sureci_sonlandir(proc)
            break
        if time.monotonic() - baslangic > zaman_asimi:
            zaman_asimi_oldu = True
            _sureci_sonlandir(proc)
            break
        time.sleep(0.05)

    okuma_thread.join(timeout=2.0)
    sure_sn = round(time.monotonic() - baslangic, 2)
    cikis_kodu = proc.returncode if proc.returncode is not None else -1

    sonraki_goruntu = _klasor_anlik_goruntu(calisma_dizin)
    degisiklikler, fark_metni = _degisiklikleri_hesapla(onceki_goruntu, sonraki_goruntu, calisma_dizin)

    ham_cikti = "".join(satirlar).strip()
    if len(ham_cikti) > MAX_OUTPUT:
        gosterilen_cikti = ham_cikti[:MAX_OUTPUT] + "\n" + t(
            "[... çıktı kırpıldı, toplam {satir} satır]", satir=len(satirlar)
        )
    else:
        gosterilen_cikti = ham_cikti

    terminal_bilgisi = {
        "komut": komut,
        "cwd": str(calisma_dizin),
        "cikis_kodu": cikis_kodu,
        "sure_sn": sure_sn,
        "zaman_asimi": zaman_asimi_oldu,
        "durduruldu": durduruldu,
        "cikti": gosterilen_cikti,
        "stdout": gosterilen_cikti,
        "stderr": "",
        "degisiklikler": degisiklikler,
        "fark": fark_metni,
    }

    if durduruldu:
        return sonuc_hatasi(
            t("Komut kullanıcı tarafından durduruldu."),
            ek={"terminal": terminal_bilgisi},
        )
    if zaman_asimi_oldu:
        metin = t("Komut {sn} sn zaman aşımına uğradı ve sonlandırıldı.", sn=zaman_asimi)
        if gosterilen_cikti:
            metin += "\n" + _sarmala(gosterilen_cikti)
        return sonuc_hatasi(metin, ek={"terminal": terminal_bilgisi})

    baslik = t("[komut: {komut} | dizin: {cwd} | çıkış kodu: {kod} | {sure} sn]",
               komut=komut, cwd=calisma_dizin, kod=cikis_kodu, sure=sure_sn)
    govde = gosterilen_cikti or t("(çıktı yok)")

    degisiklik_ozeti = ""
    if degisiklikler:
        kalemler = [
            f"{d['yol']} ({d['durum']}, +{d['eklenen']}/-{d['silinen']})"
            for d in degisiklikler[:20]
        ]
        degisiklik_ozeti = "\n" + t("Değişen dosyalar: {liste}", liste=", ".join(kalemler))

    sonuc_metni = f"{baslik}{degisiklik_ozeti}\n{_sarmala(govde)}"
    return AracSonucu(sonuc_metni, basarili=(cikis_kodu == 0), ek={"terminal": terminal_bilgisi})
