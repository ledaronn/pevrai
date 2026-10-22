"""araclar/masaustu.py — Acik masaustu programlarini kismi kontrol araclari.

Guvenlik ilkeleri:
  1. YALNIZCA ACIK PENCERELER: Bu moduldaki hicbir arac kapali bir uygulamayi
     BASLATAMAZ. Hedef pencere acik degilse hata doner ve acik pencereleri
     listeler. Program acmak yalnizca kullanici onayi isteyen open_file ile mumkundur.
  2. CIFT KATMANLI KARA LISTE: Hem kapida (gate_kurallar.masaustu_karari)
     pencere adina gore, hem de burada gercek surec kimligi (PID == os.getpid())
     ve calistirilabilir dosya adina (.exe) gore denetlenir. Boylece basligi
     degismis bir terminal penceresi veya Pevrai'nin kendi penceresi ASLA
     kontrol edilemez.
  3. PAROLA VE KART KORUMASI: Parola/sifre alanlarina ve kart/kimlik numarasi
     kaliplarina yazma reddedilir.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import sys
import time
from typing import Any

from pevrai.araclar.kayit import arac
from pevrai.araclar.ortak import hassas_mi, kirp
from pevrai.ceviri import t
from pevrai.gate_kurallar import masaustu_yasakli_mi
from pevrai.sonuc import hata as sonuc_hatasi


def _sarmala(metin: str, kaynak: str) -> str:
    temiz = re.sub(r"</\s*untrusted_content\s*>", "[/untrusted_content]", metin, flags=re.I)
    return f'<untrusted_content kaynak="{kaynak}">\n{temiz}\n</untrusted_content>'


def _surec_adi_coz(pid: int) -> str:
    """PID'den calistirilabilir dosya adini (orn. 'notepad.exe') dondurur."""
    if sys.platform != "win32" or pid <= 0:
        return ""
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h_proc = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h_proc:
            return ""
        try:
            tampon = ctypes.create_unicode_buffer(512)
            boyut = ctypes.c_ulong(512)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(h_proc, 0, tampon, ctypes.byref(boyut)):
                return os.path.basename(tampon.value)
        finally:
            ctypes.windll.kernel32.CloseHandle(h_proc)
    except Exception:
        pass
    return ""


def acik_pencereleri_listele() -> list[dict[str, Any]]:
    """Sistemdeki gorunur ust-duzey pencereleri (hwnd, pid, uygulama, baslik, konum) dondurur."""
    if sys.platform != "win32":
        return []
    user32 = ctypes.windll.user32
    pencereler: list[dict[str, Any]] = []
    kendi_pid = os.getpid()
    aktif_hwnd = user32.GetForegroundWindow()

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    def _geri_cagri(hwnd, _lparam) -> bool:
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            uzunluk = user32.GetWindowTextLengthW(hwnd)
            if uzunluk <= 0:
                return True
            tampon = ctypes.create_unicode_buffer(uzunluk + 1)
            user32.GetWindowTextW(hwnd, tampon, uzunluk + 1)
            baslik = tampon.value.strip()
            if not baslik or baslik in ("Program Manager", "Windows Input Experience", "MSCTFIME UI", "Default IME"):
                return True

            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pid_deger = int(pid.value)
            uygulama = _surec_adi_coz(pid_deger)

            rect = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            genislik = max(0, rect.right - rect.left)
            yukseklik = max(0, rect.bottom - rect.top)
            if genislik < 20 or yukseklik < 20:
                return True

            yasak = (
                t("Pevrai kendi penceresini kontrol edemez.")
                if pid_deger == kendi_pid
                else masaustu_yasakli_mi(baslik, uygulama)
            )
            pencereler.append({
                "hwnd": int(hwnd),
                "pid": pid_deger,
                "uygulama": uygulama or "?",
                "baslik": baslik,
                "sol": int(rect.left),
                "ust": int(rect.top),
                "genislik": int(genislik),
                "yukseklik": int(yukseklik),
                "aktif": bool(hwnd == aktif_hwnd),
                "korumali": bool(yasak),
                "koruma_sebebi": yasak or "",
            })
        except Exception:
            pass
        return True

    user32.EnumWindows(WNDENUMPROC(_geri_cagri), 0)
    return pencereler


def _pencere_bul(aranan: str) -> tuple[dict[str, Any] | None, str | None]:
    """Acik pencereler arasinda baslik veya uygulama adina gore pencereyi bulur.
    Pencere acik degilse veya korumaliysa (None, hata_mesaji) doner."""
    sorgu = (aranan or "").strip().casefold()
    if not sorgu:
        return None, t("Hedef pencere adı ('window') boş olamaz.")

    yasak = masaustu_yasakli_mi(sorgu)
    if yasak:
        return None, yasak

    liste = acik_pencereleri_listele()
    eslesenler = [
        p for p in liste
        if sorgu in p["baslik"].casefold() or sorgu in p["uygulama"].casefold()
    ]
    if not eslesenler:
        acik_adlar = [
            f"{p['baslik']} ({p['uygulama']})"
            for p in liste
            if not p.get("korumali")
        ][:15]
        ozet = ", ".join(acik_adlar) if acik_adlar else t("(kontrol edilebilir açık pencere yok)")
        return None, t(
            "'{pencere}' adında açık bir pencere bulunamadı. Masaüstü araçları kapalı bir programı "
            "kendi başına başlatamaz; yalnızca açık pencereleri kontrol edebilir. Şu an açık olanlar: {liste}",
            pencere=aranan,
            liste=ozet,
        )

    secilen = eslesenler[0]
    if secilen.get("korumali"):
        return None, secilen.get("koruma_sebebi") or t(
            "'{pencere}' güvenlik nedeniyle masaüstü kontrolüne kapalıdır.", pencere=secilen["baslik"]
        )
    return secilen, None


def _pencere_odakla(hwnd: int) -> bool:
    """Acik pencereyi one getirir (minimize ise restore eder)."""
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        SW_RESTORE = 9
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(0.1)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.08)
        return True
    except Exception:
        return False


def _pencere_ogelerini_oku(hwnd: int) -> list[dict[str, Any]]:
    """UI Automation ve Win32 alt pencereleri uzerinden penceredeki etkilesimli ogeleri okur."""
    ogeler: list[dict[str, Any]] = []
    if sys.platform != "win32":
        return ogeler

    # 1) UI Automation ile buton, metin kutusu, menu ve etiketleri oku
    ps_betik = f"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$el = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]{int(hwnd)})
if ($null -ne $el) {{
    $all = $el.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    $out = @()
    $limit = [Math]::Min($all.Count, 120)
    for ($i = 0; $i -lt $limit; $i++) {{
        $item = $all[$i]
        $c = $item.Current
        $name = $c.Name
        $type = $c.ControlType.ProgrammaticName -replace '^ControlType\\.', ''
        if ([string]::IsNullOrWhiteSpace($name) -and $type -notin @('Edit', 'Document')) {{ continue }}
        $r = $c.BoundingRectangle
        if ($r.Width -le 0 -or $r.Height -le 0) {{ continue }}
        $out += [PSCustomObject]@{{
            rol = $type.ToLower()
            ad = [string]$name
            x = [int]($r.Left + $r.Width / 2)
            y = [int]($r.Top + $r.Height / 2)
        }}
    }}
    $out | ConvertTo-Json -Compress
}}
"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_betik],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        cikti = (r.stdout or "").strip()
        if cikti:
            veri = json.loads(cikti)
            if isinstance(veri, dict):
                veri = [veri]
            if isinstance(veri, list):
                for o in veri[:80]:
                    if isinstance(o, dict):
                        ogeler.append({
                            "rol": str(o.get("rol") or "oge"),
                            "ad": str(o.get("ad") or "").strip(),
                            "x": int(o.get("x") or 0),
                            "y": int(o.get("y") or 0),
                        })
    except Exception:
        pass

    if ogeler:
        return ogeler

    # 2) Yedek: Win32 EnumChildWindows
    try:
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        def _alt_geri_cagri(c_hwnd, _lparam) -> bool:
            if len(ogeler) >= 80:
                return False
            if not user32.IsWindowVisible(c_hwnd):
                return True
            sinif_buf = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(c_hwnd, sinif_buf, 128)
            uzunluk = user32.GetWindowTextLengthW(c_hwnd)
            metin_buf = ctypes.create_unicode_buffer(min(uzunluk + 1, 256))
            if uzunluk > 0:
                user32.GetWindowTextW(c_hwnd, metin_buf, min(uzunluk + 1, 256))
            rect = RECT()
            user32.GetWindowRect(c_hwnd, ctypes.byref(rect))
            ad = metin_buf.value.strip()
            sinif = sinif_buf.value.strip()
            if ad or sinif.lower() in ("edit", "richedit20w", "richedit50w", "scintilla"):
                ogeler.append({
                    "rol": sinif.lower() or "oge",
                    "ad": ad,
                    "x": int((rect.left + rect.right) // 2),
                    "y": int((rect.top + rect.bottom) // 2),
                })
            return True

        user32.EnumChildWindows(hwnd, WNDENUMPROC(_alt_geri_cagri), 0)
    except Exception:
        pass
    return ogeler


def _fare_tikla(ekran_x: int, ekran_y: int) -> bool:
    """Belirtilen ekran koordinatina sol tiklar."""
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        user32.SetCursorPos(int(ekran_x), int(ekran_y))
        time.sleep(0.04)
        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.03)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        return True
    except Exception:
        return False


_SENDKEYS_HARITA = {
    "enter": "{ENTER}",
    "return": "{ENTER}",
    "tab": "{TAB}",
    "esc": "{ESC}",
    "escape": "{ESC}",
    "space": " ",
    "backspace": "{BS}",
    "delete": "{DEL}",
    "del": "{DEL}",
    "up": "{UP}",
    "down": "{DOWN}",
    "left": "{LEFT}",
    "right": "{RIGHT}",
    "home": "{HOME}",
    "end": "{END}",
    "pageup": "{PGUP}",
    "pgup": "{PGUP}",
    "pagedown": "{PGDN}",
    "pgdn": "{PGDN}",
    "f1": "{F1}", "f2": "{F2}", "f3": "{F3}", "f4": "{F4}",
    "f5": "{F5}", "f6": "{F6}", "f7": "{F7}", "f8": "{F8}",
    "f9": "{F9}", "f10": "{F10}", "f11": "{F11}", "f12": "{F12}",
}


def _sendkeys_ifadesi_kur(tus: str) -> str:
    """'Ctrl+F', 'Alt+F4', 'Enter' gibi tus dizgesini WScript.Shell SendKeys bicimine cevirir."""
    parcalar = [p.strip().lower() for p in tus.split("+") if p.strip()]
    if not parcalar:
        return ""
    on_ek = ""
    ana_tus = parcalar[-1]
    for mod in parcalar[:-1]:
        if mod in ("ctrl", "control"):
            on_ek += "^"
        elif mod == "alt":
            on_ek += "%"
        elif mod == "shift":
            on_ek += "+"
    karsilik = _SENDKEYS_HARITA.get(ana_tus)
    if karsilik is None:
        if len(ana_tus) == 1 and ana_tus.isalnum():
            karsilik = ana_tus
        else:
            return ""
    return on_ek + karsilik


def _sendkeys_gonder(ifade: str) -> bool:
    if sys.platform != "win32" or not ifade:
        return False
    guvenli = ifade.replace("'", "''")
    betik = f"$ws = New-Object -ComObject WScript.Shell; $ws.SendKeys('{guvenli}')"
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", betik],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return r.returncode == 0
    except Exception:
        return False


def _metin_sendkeys_kacisla(metin: str) -> str:
    """Duz metni SendKeys ozel karakterlerinden ({}+^%~()) kacislar."""
    cikti: list[str] = []
    for ch in metin:
        if ch in "{}+^%~()[]":
            cikti.append("{" + ch + "}")
        elif ch == "\n":
            cikti.append("{ENTER}")
        elif ch == "\r":
            continue
        elif ch == "\t":
            cikti.append("{TAB}")
        else:
            cikti.append(ch)
    return "".join(cikti)


@arac(
    ad="window_list",
    paket="masaustu",
    risk="READ",
    baslik="Açık pencereleri listeleme",
    aciklama="Bilgisayarda şu an açık olan görünür program pencerelerini listeler.",
    modele=(
        "Bilgisayarda ŞU AN AÇIK olan masaüstü pencerelerini (başlık, uygulama adı ve durum) "
        "listeler. Bir programı kontrol etmeden önce açık olup olmadığını ve tam pencere "
        "başlığını öğrenmek için çağır. Kapalı bir programı başlatamaz."
    ),
)
def window_list(yol, args: dict) -> str:
    if sys.platform != "win32":
        return sonuc_hatasi(t("Masaüstü kontrol araçları yalnızca Windows'ta çalışır."))
    liste = acik_pencereleri_listele()
    if not liste:
        return t("(açık pencere bulunamadı)")
    satirlar = []
    for p in liste:
        durum = t(" [AKTİF]") if p.get("aktif") else ""
        koruma = f" [{t('korumalı — erişilemez')}]" if p.get("korumali") else ""
        satirlar.append(
            f"- {p['baslik']} ({p['uygulama']}, {p['genislik']}x{p['yukseklik']}){durum}{koruma}"
        )
    return _sarmala("\n".join(satirlar), "window_list")


@arac(
    ad="window_read",
    paket="masaustu",
    risk="READ",
    baslik="Açık pencereyi okuma",
    aciklama="Açık bir program penceresindeki butonları, metin kutularını ve yazıları okur.",
    modele=(
        "Açık bir masaüstü penceresinin içindeki etkileşimli ögeleri (buton, metin kutusu, menü, "
        "etiket) ve konumlarını okur. window_click ve window_type çağırmadan önce penceredeki "
        "ögeleri görmek için kullan. Yalnızca açık pencerelerde çalışır; kapalı programı açmaz. "
        "Çıktı <untrusted_content> içindedir."
    ),
    sema={
        "type": "object",
        "properties": {
            "window": {
                "type": "string",
                "description": "Hedef pencerenin başlığı veya uygulama adı (window_list çıktısından).",
            },
        },
        "required": ["window"],
    },
)
def window_read(yol, args: dict) -> str:
    if sys.platform != "win32":
        return sonuc_hatasi(t("Masaüstü kontrol araçları yalnızca Windows'ta çalışır."))
    aranan = str((args or {}).get("window", "")).strip()
    pencere, hata = _pencere_bul(aranan)
    if hata or pencere is None:
        return sonuc_hatasi(hata or t("Pencere bulunamadı."))

    ogeler = _pencere_ogelerini_oku(pencere["hwnd"])
    baslik_satiri = (
        f"Pencere: {pencere['baslik']} ({pencere['uygulama']})\n"
        f"Boyut: {pencere['genislik']}x{pencere['yukseklik']} (sol={pencere['sol']}, üst={pencere['ust']})"
    )
    if not ogeler:
        govde = baslik_satiri + "\n" + t("(etkileşimli alt öge okunamadı; göreli koordinat veya tuş kullanılabilir)")
    else:
        satirlar = [baslik_satiri, t("Ögeler:")]
        for o in ogeler[:80]:
            goreli_x = max(0, o["x"] - pencere["sol"])
            goreli_y = max(0, o["y"] - pencere["ust"])
            ad_gosterim = f"'{o['ad']}'" if o["ad"] else t("(adsız)")
            satirlar.append(f"  [{o['rol']}] {ad_gosterim} (x={goreli_x}, y={goreli_y})")
        govde = "\n".join(satirlar)
    return kirp(_sarmala(govde, "window_read"), govde.count("\n") + 1)


@arac(
    ad="window_click",
    paket="masaustu",
    risk="WRITE_HAFIF",
    baslik="Pencerede tıklama",
    aciklama="Açık bir program penceresindeki ögeye adıyla veya pencere içi koordinatla tıklar.",
    modele=(
        "Açık bir masaüstü penceresini öne getirir ve içindeki bir ögeye ('name' ile) ya da "
        "pencere içi göreli koordinata ('x', 'y') tıklar. Yalnızca açık pencerelerde çalışır; "
        "kapalı programı başlatmaz. İlk etkileşimde ve Sil/Gönder/Kaydet/Kapat gibi kritik "
        "düğmelerde kullanıcıdan onay ister."
    ),
    sema={
        "type": "object",
        "properties": {
            "window": {
                "type": "string",
                "description": "Hedef pencerenin başlığı veya uygulama adı.",
            },
            "name": {
                "type": "string",
                "description": "Tıklanacak ögenin adı (window_read çıktısından). Koordinat veriliyorsa boş bırakılabilir.",
            },
            "x": {
                "type": "integer",
                "description": "İsteğe bağlı: pencerenin sol üst köşesine göre yatay koordinat (piksel).",
            },
            "y": {
                "type": "integer",
                "description": "İsteğe bağlı: pencerenin sol üst köşesine göre dikey koordinat (piksel).",
            },
        },
        "required": ["window"],
    },
)
def window_click(yol, args: dict) -> str:
    if sys.platform != "win32":
        return sonuc_hatasi(t("Masaüstü kontrol araçları yalnızca Windows'ta çalışır."))
    args = args or {}
    aranan = str(args.get("window", "")).strip()
    pencere, hata = _pencere_bul(aranan)
    if hata or pencere is None:
        return sonuc_hatasi(hata or t("Pencere bulunamadı."))

    ad = str(args.get("name", "")).strip()
    x_arg, y_arg = args.get("x"), args.get("y")

    hedef_x: int | None = None
    hedef_y: int | None = None

    if ad:
        ogeler = _pencere_ogelerini_oku(pencere["hwnd"])
        aranan_ad = ad.casefold()
        eslesen = next((o for o in ogeler if o["ad"].casefold() == aranan_ad), None)
        if eslesen is None:
            eslesen = next((o for o in ogeler if aranan_ad in o["ad"].casefold()), None)
        if eslesen is None:
            mevcut = ", ".join(f"'{o['ad']}'" for o in ogeler if o["ad"])[:200] or t("(yok)")
            return sonuc_hatasi(t(
                "'{pencere}' penceresinde '{ad}' ögesi bulunamadı. Mevcut ögeler: {liste}",
                pencere=pencere["baslik"], ad=ad, liste=mevcut,
            ))
        hedef_x, hedef_y = eslesen["x"], eslesen["y"]
    elif x_arg is not None and y_arg is not None:
        try:
            gx, gy = int(x_arg), int(y_arg)
        except (TypeError, ValueError):
            return sonuc_hatasi(t("Geçersiz koordinat değerleri."))
        if not (0 <= gx <= pencere["genislik"] and 0 <= gy <= pencere["yukseklik"]):
            return sonuc_hatasi(t(
                "Koordinat ({x}, {y}) pencere sınırlarının ({g}x{yuk}) dışında.",
                x=gx, y=gy, g=pencere["genislik"], yuk=pencere["yukseklik"],
            ))
        hedef_x = pencere["sol"] + gx
        hedef_y = pencere["ust"] + gy
    else:
        return sonuc_hatasi(t("window_click için 'name' (öge adı) ya da 'x' ve 'y' koordinatı verilmelidir."))

    _pencere_odakla(pencere["hwnd"])
    if not _fare_tikla(hedef_x, hedef_y):
        return sonuc_hatasi(t("'{pencere}' penceresinde tıklama gerçekleştirilemedi.", pencere=pencere["baslik"]))
    etiket = f"'{ad}'" if ad else f"({x_arg}, {y_arg})"
    return t("'{pencere}' penceresinde {hedef} konumuna tıklandı.", pencere=pencere["baslik"], hedef=etiket)


@arac(
    ad="window_type",
    paket="masaustu",
    risk="WRITE_HAFIF",
    baslik="Pencereye metin yazma",
    aciklama="Açık bir program penceresine veya metin alanına yazı yazar; parola ve kart bilgisini reddeder.",
    modele=(
        "Açık bir masaüstü penceresine metin yazar. İsteğe bağlı 'name' verilirse önce o metin "
        "kutusuna tıklar. Parola alanlarına ve kart/kimlik numarası içeren metinlere yazmaz. "
        "Yalnızca açık pencerelerde çalışır."
    ),
    sema={
        "type": "object",
        "properties": {
            "window": {
                "type": "string",
                "description": "Hedef pencerenin başlığı veya uygulama adı.",
            },
            "text": {
                "type": "string",
                "description": "Yazılacak metin.",
            },
            "name": {
                "type": "string",
                "description": "İsteğe bağlı: yazmadan önce tıklanacak metin alanının adı.",
            },
            "submit": {
                "type": "boolean",
                "description": "Yazdıktan sonra Enter tuşuna basılsın mı (varsayılan false).",
            },
        },
        "required": ["window", "text"],
    },
)
def window_type(yol, args: dict) -> str:
    if sys.platform != "win32":
        return sonuc_hatasi(t("Masaüstü kontrol araçları yalnızca Windows'ta çalışır."))
    args = args or {}
    aranan = str(args.get("window", "")).strip()
    metin = str(args.get("text", ""))
    ad = str(args.get("name", "")).strip()
    submit = bool(args.get("submit"))

    sebep = hassas_mi(metin)
    if sebep:
        return sonuc_hatasi(t(
            "Reddedildi: girilecek metin {sebep} içeriyor. Ajan kimlik veya ödeme bilgisi girmez.",
            sebep=sebep,
        ))

    pencere, hata = _pencere_bul(aranan)
    if hata or pencere is None:
        return sonuc_hatasi(hata or t("Pencere bulunamadı."))

    _pencere_odakla(pencere["hwnd"])
    if ad:
        ogeler = _pencere_ogelerini_oku(pencere["hwnd"])
        aranan_ad = ad.casefold()
        eslesen = next((o for o in ogeler if aranan_ad in o["ad"].casefold()), None)
        if eslesen is not None:
            _fare_tikla(eslesen["x"], eslesen["y"])
            time.sleep(0.06)

    ifade = _metin_sendkeys_kacisla(metin)
    if submit:
        ifade += "{ENTER}"
    if not _sendkeys_gonder(ifade):
        return sonuc_hatasi(t("'{pencere}' penceresine metin gönderilemedi.", pencere=pencere["baslik"]))
    return t("'{pencere}' penceresine metin yazıldı ({uzunluk} karakter).",
             pencere=pencere["baslik"], uzunluk=len(metin))


@arac(
    ad="window_key",
    paket="masaustu",
    risk="WRITE_HAFIF",
    baslik="Pencereye tuş gönderme",
    aciklama="Açık bir program penceresine klavye tuşu veya kısayol (örn. Ctrl+F, Escape, Tab) gönderir.",
    modele=(
        "Açık bir masaüstü penceresini öne getirir ve bir klavye tuşu veya kısayolu (örn. 'Ctrl+F', "
        "'Tab', 'Escape', 'Enter', 'Down') gönderir. Yalnızca açık pencerelerde çalışır. "
        "Alt+F4, Ctrl+W, Delete, Ctrl+S gibi kritik kısayollar her zaman kullanıcı onayı ister."
    ),
    sema={
        "type": "object",
        "properties": {
            "window": {
                "type": "string",
                "description": "Hedef pencerenin başlığı veya uygulama adı.",
            },
            "key": {
                "type": "string",
                "description": "Gönderilecek tuş veya kısayol (örn. 'Ctrl+F', 'Enter', 'Tab', 'Escape', 'Down').",
            },
        },
        "required": ["window", "key"],
    },
)
def window_key(yol, args: dict) -> str:
    if sys.platform != "win32":
        return sonuc_hatasi(t("Masaüstü kontrol araçları yalnızca Windows'ta çalışır."))
    args = args or {}
    aranan = str(args.get("window", "")).strip()
    tus = str(args.get("key") or args.get("keys") or "").strip()

    pencere, hata = _pencere_bul(aranan)
    if hata or pencere is None:
        return sonuc_hatasi(hata or t("Pencere bulunamadı."))

    ifade = _sendkeys_ifadesi_kur(tus)
    if not ifade:
        return sonuc_hatasi(t("'{tus}' geçerli veya desteklenen bir tuş dizisi değil.", tus=tus))

    _pencere_odakla(pencere["hwnd"])
    if not _sendkeys_gonder(ifade):
        return sonuc_hatasi(t("'{pencere}' penceresine '{tus}' tuşu gönderilemedi.",
                              pencere=pencere["baslik"], tus=tus))
    return t("'{pencere}' penceresine '{tus}' tuşu gönderildi.", pencere=pencere["baslik"], tus=tus)
