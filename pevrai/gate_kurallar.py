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


# ---------------------------------------------------------------------------
# Terminal izin kurallari (Claude Code tarzi katmanli kapi)
# ---------------------------------------------------------------------------

import shlex
from fnmatch import fnmatch

# Kabuk zincirleme / yonlendirme / alt kabuk isaretleri: bunlardan biri varsa
# komut ASLA dogrudan ALLOW almaz (en iyi ihtimalle ASK, yasak hedef varsa DENY).
KABUK_ZINCIR_KARAKTERLERI = ("|", ">", "<", "&", ";", "`", "$(", "\n", "\r")

# Kesinlikle yasak sistem ve disk komutlari (DENY).
TERMINAL_YASAK_KOMUTLAR = frozenset({
    "format", "diskpart", "bcdedit", "cipher", "vssadmin", "wbadmin",
    "regedit", "takeown", "icacls", "cacls", "shutdown", "restart-computer",
    "stop-computer", "clear-disk", "initialize-disk", "format-volume",
    "set-executionpolicy", "add-mppreference", "set-mppreference",
})

TERMINAL_YASAK_IFADELER = (
    "reg delete", "reg add", "sc delete", "sc stop", "net user", "net localgroup",
    "-encodedcommand", "-enc ", "frombase64string", "invoke-expression",
    "downloadstring", "downloadfile", "start-bitstransfer",
    "policy.toml", "credentials.json", ".vekil", "persona.md",
)

# Yikici terminal komutlari: onay kartinda kirmizi uyari gosterir ve
# "Bu oturumda sorma" (toplu onay) secenegini kapatir — her seferinde tek tek sorar.
TERMINAL_YIKICI_KOMUTLAR = frozenset({
    "rm", "del", "erase", "rd", "rmdir", "remove-item", "ri",
    "taskkill", "stop-process", "kill", "clear-content", "clc",
})

TERMINAL_YIKICI_IFADELER = (
    "git reset --hard", "git clean", "git push --force", "git push -f",
    "git branch -d", "git branch -D", "git checkout --", "shutil.rmtree",
)

# Dogrudan calisabilen (ALLOW) salt-okuma komutlari (zincirleme/yonlendirme yoksa).
TERMINAL_OKUMA_KOMUTLARI = frozenset({
    "dir", "ls", "get-childitem", "gci", "pwd", "get-location", "gl",
    "echo", "write-output", "type", "cat", "get-content", "gc",
    "findstr", "select-string", "sls", "where", "where.exe", "which",
    "whoami", "hostname", "ver", "tree", "get-date", "date", "time", "measure-object",
})

GIT_OKUMA_ALT_KOMUTLARI = frozenset({
    "status", "diff", "log", "show", "branch", "rev-parse",
    "ls-files", "remote", "tag", "describe", "shortlog", "blame",
})

GIT_YAZMA_BAYRAKLARI = frozenset({
    "-d", "-D", "--delete", "-f", "--force", "-m", "--move", "-c", "-C",
    "--output", "-o", "add", "set-url", "remove", "rename", "prune",
})


def _parcalara_ayir(komut: str) -> list[str]:
    try:
        parcalar = shlex.split(komut, posix=False)
    except ValueError:
        parcalar = komut.split()
    return [p.strip("\"'") for p in parcalar if p.strip("\"'")]


def _komut_adini_coz(ilk: str) -> str:
    ad = Path(ilk).name.lower()
    if ad.endswith((".exe", ".cmd", ".bat", ".ps1")):
        ad = ad.rsplit(".", 1)[0]
    return ad


def terminal_komut_anahtari(komut: str) -> str:
    """Oturum ici komut onayi icin kanonik anahtar (orn. 'pytest', 'npm test', 'python')."""
    parcalar = _parcalara_ayir(komut)
    if not parcalar:
        return ""
    ilk = _komut_adini_coz(parcalar[0])
    if ilk in ("git", "npm", "pip", "uv", "cargo", "dotnet", "go") and len(parcalar) >= 2:
        ikinci = parcalar[1].lower()
        if not ikinci.startswith("-"):
            return f"{ilk} {ikinci}"
    return ilk


def terminal_yikici_mi(komut: str) -> bool:
    """Komut dosya siliyor ya da geri alinamaz bir degisiklik yapiyor mu?"""
    kucuk = (komut or "").strip().lower()
    if not kucuk:
        return False
    if any(ifade in kucuk for ifade in TERMINAL_YIKICI_IFADELER):
        return True
    for parca in re.split(r"[|;&\n\r]+", kucuk):
        kelimeler = _parcalara_ayir(parca)
        if not kelimeler:
            continue
        ad = _komut_adini_coz(kelimeler[0])
        if ad in TERMINAL_YIKICI_KOMUTLAR:
            return True
    return False


def _yol_benzeri_mi(token: str) -> bool:
    if not token or token.startswith("-"):
        return False
    if ".." in token or token.startswith(("~", "./", ".\\", "/", "\\")):
        return True
    if re.match(r"^[A-Za-z]:[\\/]", token):
        return True
    return "/" in token or "\\" in token


def terminal_karari(komut: str, cwd: str,
                    okuma_kokleri: Iterable[Path],
                    yazma_kokleri: Iterable[Path],
                    yasak_kaliplar: Iterable[str],
                    proje_koku: Path,
                    varsayilan_cwd: Path | None = None) -> Karar:
    """Terminal komutu icin (ALLOW | ASK | DENY, gerekce, cozulmus_cwd)."""
    okuma = [Path(p).expanduser().resolve() for p in okuma_kokleri]
    yazma = [Path(p).expanduser().resolve() for p in yazma_kokleri]
    izinli_kokler = list(dict.fromkeys(yazma + okuma))
    yasak = [str(k).lower() for k in yasak_kaliplar]

    if not izinli_kokler:
        return Karar(DENY, t("Terminal için izinli bir çalışma veya okuma klasörü tanımlı değil."))

    ham_cwd = (cwd or "").strip()
    if ham_cwd:
        aday = Path(ham_cwd).expanduser()
        if aday.drive and not aday.is_absolute():
            return Karar(DENY, t("'{yol}' geçerli bir çalışma dizini değil.", yol=ham_cwd))
        if not aday.is_absolute():
            taban = varsayilan_cwd or (yazma[0] if yazma else okuma[0])
            aday = taban / aday
    else:
        aday = varsayilan_cwd or (yazma[0] if yazma else okuma[0])

    try:
        cozulmus_cwd = aday.resolve()
    except (OSError, ValueError):
        return Karar(DENY, t("'{yol}' geçerli bir çalışma dizini değil.", yol=ham_cwd or str(aday)))

    tuzak = windows_ad_tuzagi(cozulmus_cwd)
    if tuzak:
        return Karar(DENY, t("'{yol}' reddedildi: {sebep}.", yol=cozulmus_cwd, sebep=tuzak))

    from pevrai import DONMUS, KAYNAK_KOK, PAKET
    korunan_kokler = [PAKET.resolve(), (Path(proje_koku) / "config").resolve()]
    if DONMUS:
        try:
            korunan_kokler.append(KAYNAK_KOK.resolve())
        except OSError:
            pass
    for k in korunan_kokler:
        if cozulmus_cwd == k or k in cozulmus_cwd.parents:
            return Karar(DENY, t("Terminal Pevrai'nın kendi kaynak veya ayar klasöründe çalıştırılamaz."))

    for parca in cozulmus_cwd.parts:
        for kalip in yasak:
            if fnmatch(parca.lower(), kalip):
                return Karar(DENY, t("'{yol}' kara listede ('{kalip}' kalıbı).", yol=cozulmus_cwd, kalip=kalip))

    if not any(cozulmus_cwd == k or k in cozulmus_cwd.parents for k in izinli_kokler):
        liste = ", ".join(str(k) for k in izinli_kokler)
        return Karar(DENY, t("'{yol}' izinli klasörlerin dışında. İzinli olanlar: {liste}",
                             yol=cozulmus_cwd, liste=liste))

    metin = (komut or "").strip()
    if not metin:
        return Karar(DENY, t("Çalıştırılacak komut boş olamaz."))
    if "\x00" in metin:
        return Karar(DENY, t("Komut geçersiz NUL baytı içeriyor."))

    kucuk = metin.lower()
    # Kendi kaynak koduna, policy.toml'a ve gizli dosyalara erisim kontrolu
    for korunan in korunan_kokler:
        k_str = str(korunan).lower()
        k_posix = korunan.as_posix().lower()
        if k_str in kucuk or k_posix in kucuk:
            return Karar(DENY, t("Komut Pevrai'nın kendi korunan klasörüne erişemez."))

    for ifade in TERMINAL_YASAK_IFADELER:
        if ifade in kucuk:
            return Karar(DENY, t("Güvenlik kuralı: '{ifade}' içeren terminal komutu yasaktır.", ifade=ifade))

    parcalar = _parcalara_ayir(metin)
    if not parcalar:
        return Karar(DENY, t("Çalıştırılacak komut boş olamaz."))

    # Alt komutlarda ve argumanlarda yasak komut / kara liste / yol kacisi denetimi
    for alt_komut in re.split(r"[|;&\n\r]+", metin):
        alt_parcalar = _parcalara_ayir(alt_komut)
        if not alt_parcalar:
            continue
        ilk_ad = _komut_adini_coz(alt_parcalar[0])
        if ilk_ad in TERMINAL_YASAK_KOMUTLAR:
            return Karar(DENY, t("Güvenlik kuralı: '{komut}' sistem komutu yasaktır.", komut=ilk_ad))
        if ilk_ad in ("iex", "invoke-expression"):
            return Karar(DENY, t("Güvenlik kuralı: dinamik kod çalıştırma ('{komut}') yasaktır.", komut=ilk_ad))

    for tok in parcalar:
        tok_kucuk = tok.lower()
        # Kara liste kalibi kontrolu (orn. .env, *.pem, id_rsa)
        tok_dosya = Path(tok.rstrip("/\\")).name.lower()
        for kalip in yasak:
            if tok_dosya and fnmatch(tok_dosya, kalip):
                return Karar(DENY, t("Komut kara listedeki bir dosyaya ('{kalip}') erişmeye çalışıyor.", kalip=kalip))
        # Yol benzeri argumanlarin izinli kokler icinde kalmasi
        if _yol_benzeri_mi(tok):
            try:
                p_aday = Path(tok).expanduser()
                p_coz = (p_aday if p_aday.is_absolute() else (cozulmus_cwd / p_aday)).resolve()
            except (OSError, ValueError):
                continue
            for korunan in korunan_kokler:
                if p_coz == korunan or korunan in p_coz.parents:
                    return Karar(DENY, t("Komut Pevrai'nın kendi klasörüne erişemez: '{yol}'", yol=tok))
            for parca in p_coz.parts:
                for kalip in yasak:
                    if fnmatch(parca.lower(), kalip):
                        return Karar(DENY, t("'{yol}' kara listede ('{kalip}' kalıbı).", yol=tok, kalip=kalip))
            if not any(p_coz == k or k in p_coz.parents for k in izinli_kokler):
                return Karar(DENY, t("Komut izinli klasörlerin dışındaki bir yola erişmeye çalışıyor: '{yol}'", yol=tok))

    # Salt-okuma (ALLOW) kontrolu: kabuk zinciri/yonlendirmesi yoksa ve guvenli okuma komutuysa
    zincir_var = any(k in metin for k in KABUK_ZINCIR_KARAKTERLERI)
    ilk = _komut_adini_coz(parcalar[0])
    guvenli_okuma = False
    if not zincir_var:
        if ilk in TERMINAL_OKUMA_KOMUTLARI:
            guvenli_okuma = True
        elif ilk == "git" and len(parcalar) >= 2:
            alt = parcalar[1].lower()
            if alt in GIT_OKUMA_ALT_KOMUTLARI and not any(p in GIT_YAZMA_BAYRAKLARI for p in parcalar[2:]):
                guvenli_okuma = True
        elif ilk in ("pytest", "py.test"):
            guvenli_okuma = True
        elif ilk in ("python", "python3", "py"):
            if len(parcalar) == 2 and parcalar[1] in ("--version", "-V", "--help", "-h"):
                guvenli_okuma = True
            elif len(parcalar) >= 3 and parcalar[1] == "-m" and parcalar[2] in ("pytest", "unittest"):
                guvenli_okuma = True
        elif ilk in ("node", "npm", "pip", "uv", "cargo", "go", "dotnet", "rustc", "gcc", "clang"):
            if len(parcalar) == 2 and parcalar[1] in ("--version", "-v", "-V", "--help", "-h"):
                guvenli_okuma = True
            elif ilk == "pip" and len(parcalar) >= 2 and parcalar[1].lower() in ("list", "show", "freeze", "check"):
                guvenli_okuma = True
            elif ilk == "npm" and len(parcalar) >= 2 and parcalar[1].lower() in ("list", "ls", "outdated"):
                guvenli_okuma = True

    if guvenli_okuma:
        return Karar(ALLOW, t("güvenli okuma komutu"), cozulmus_cwd)

    # Degistiren / calistiran komutlar YALNIZCA yazma koklerinde calisabilir
    if not any(cozulmus_cwd == y or y in cozulmus_cwd.parents for y in yazma):
        return Karar(DENY, t("'{yol}' yazılabilir bir klasör değil; değiştiren komutlar yalnızca yazma köklerinde çalışır.",
                             yol=cozulmus_cwd))

    return Karar(ASK, t("komut çalıştırma onayı gerekiyor"), cozulmus_cwd)


# ---------------------------------------------------------------------------
# Masaustu uygulama kontrolu kurallari (yalnizca acik pencereler)
# ---------------------------------------------------------------------------

# Pevrai'nin kendi penceresi, terminaller, sistem/guvenlik araclari ve parola
# yoneticileri KESINLIKLE DENY alir. Ajan kendi onay dugmesine tiklayamaz ve
# acik bir terminal penceresine komut yazarak terminal_run kapisini atlayamaz.
MASAUSTU_YASAK_PENCERELER = (
    "pevrai", "pywebview",
    "cmd.exe", "komut istemi", "command prompt", "powershell", "pwsh",
    "windowsterminal", "wt.exe", "conhost", "wsl", "git bash", "bash.exe", "mingw",
    "görev yöneticisi", "gorev yoneticisi", "task manager", "taskmgr",
    "regedit", "kayıt defteri", "kayit defteri", "registry editor",
    "kullanıcı hesabı denetimi", "user account control", "consent.exe",
    "windows güvenliği", "windows security", "defender",
    "keepass", "bitwarden", "1password", "lastpass", "dashlane",
    "kimlik bilgileri yöneticisi", "credential manager",
    "mmc.exe", "services.msc", "gpedit", "secpol",
)

MASAUSTU_KRITIK_KALIPLAR = (
    "sil", "delete", "remove", "kaldır", "kaldir",
    "gönder", "gonder", "submit", "send", "paylaş", "paylas", "yayınla", "yayinla",
    "kaydet", "save", "kapat", "close", "çıkış", "cikis", "exit", "quit",
    "onayla", "confirm", "kabul", "accept", "sıfırla", "sifirla", "reset",
)

MASAUSTU_KRITIK_TUSLAR = frozenset({
    "alt+f4", "ctrl+w", "ctrl+q", "delete", "del", "shift+delete", " shift+del",
    "ctrl+s", "ctrl+shift+s", "ctrl+enter", "alt+enter",
})

MASAUSTU_PAROLA_ALANLARI = (
    "parola", "şifre", "sifre", "password", "passcode", "pin",
    "cvv", "cvc", "kart numarası", "card number", "iban", "secret", "api key", "token",
)


def masaustu_yasakli_mi(pencere: str, islem_adi: str = "") -> str | None:
    """Hedef pencere ya da surec adi korumali/yasakli mi? Yasakliysa sebep doner."""
    birlesik = f"{pencere or ''} {islem_adi or ''}".strip().casefold()
    if not birlesik:
        return None
    for yasak in MASAUSTU_YASAK_PENCERELER:
        if yasak in birlesik:
            if yasak in ("pevrai", "pywebview"):
                return t("Pevrai kendi penceresini kontrol edemez.")
            if yasak in ("cmd.exe", "komut istemi", "command prompt", "powershell", "pwsh",
                         "windowsterminal", "wt.exe", "conhost", "wsl", "git bash", "bash.exe", "mingw"):
                return t("Terminal pencereleri masaüstü aracıyla kontrol edilemez; terminal_run aracını kullan.")
            return t("'{pencere}' güvenlik nedeniyle masaüstü kontrolüne kapalıdır.", pencere=pencere or islem_adi)
    # Tam kelime olarak 'cmd' veya 'wt'
    kelimeler = [k for k in re.split(r"[^\w.]+", birlesik) if k]
    if any(k in ("cmd", "wt", "bash", "sh", "uac") for k in kelimeler):
        return t("'{pencere}' güvenlik nedeniyle masaüstü kontrolüne kapalıdır.", pencere=pencere or islem_adi)
    return None


def masaustu_yikici_mi(arac: str, args: dict) -> bool:
    """Masaustu eylemi kritik bir islem mi (Sil/Gonder/Kaydet/Kapat/Alt+F4)?
    Kritik islemler oturumda pencere onaylanmis olsa bile HER SEFERINDE onay ister."""
    args = args or {}
    if arac == "window_click":
        ad = str(args.get("name", "")).strip().casefold()
        return any(k in ad for k in MASAUSTU_KRITIK_KALIPLAR)
    if arac == "window_type":
        return bool(args.get("submit"))
    if arac == "window_key":
        tus = str(args.get("key") or args.get("keys") or "").strip().casefold().replace(" ", "")
        return tus in MASAUSTU_KRITIK_TUSLAR
    return False


def masaustu_karari(arac: str, args: dict) -> Karar:
    """window_* araclari icin kapi karari."""
    args = args or {}
    if arac == "window_list":
        return Karar(ALLOW, t("açık pencereleri listeleme"))

    pencere = str(args.get("window", "")).strip()
    if not pencere:
        return Karar(DENY, t("Hedef pencere adı ('window') boş olamaz."))

    yasak_sebep = masaustu_yasakli_mi(pencere)
    if yasak_sebep:
        return Karar(DENY, yasak_sebep)

    if arac == "window_read":
        return Karar(ALLOW, t("açık pencereyi okuma"))

    if arac == "window_click":
        hedef = str(args.get("name", "")).strip().casefold()
        for kalip in ("satın al", "satin al", "buy", "purchase", "checkout",
                      "sipariş", "siparis", "ödeme", "odeme", "payment", "havale", "eft"):
            if kalip in hedef:
                return Karar(DENY, t("Masaüstü kontrolünde ödeme ve satın alma düğmelerine tıklamak yasaktır."))
        return Karar(ASK, t("'{pencere}' penceresinde tıklama onayı gerekiyor.", pencere=pencere))

    if arac == "window_type":
        alan = str(args.get("name", "")).strip().casefold()
        if any(p in alan for p in MASAUSTU_PAROLA_ALANLARI):
            return Karar(DENY, t("Parola, şifre ve kart alanlarına masaüstü aracıyla yazılamaz."))
        return Karar(ASK, t("'{pencere}' penceresine metin yazma onayı gerekiyor.", pencere=pencere))

    if arac == "window_key":
        tus = str(args.get("key") or args.get("keys") or "").strip()
        if not tus:
            return Karar(DENY, t("Gönderilecek tuş ('key') boş olamaz."))
        return Karar(ASK, t("'{pencere}' penceresine tuş gönderme onayı gerekiyor.", pencere=pencere))

    return Karar(DENY, t("Bilinmeyen masaüstü aracı: {arac}", arac=arac))
