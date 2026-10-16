"""TOML metin manipülasyon yardımcıları.

policy.toml'un yorumlarını, elle yazılmış düzenini ve sırasını koruyarak
yalnızca hedeflenen anahtarları ve dizileri güvenle değiştirir.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_ALAN_KALIBI = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]*[a-z0-9])?"
                          r"(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def alan_gecerli(alan: str) -> bool:
    """Alan adi bicimi. Yol enjeksiyonu ve bosluklu girdiler burada durur."""
    return bool(_ALAN_KALIBI.match((alan or "").strip().lower()))


def _toml_deger(d: Any) -> str:
    if isinstance(d, bool):
        return "true" if d else "false"
    if isinstance(d, (int, float)):
        return str(d)
    return '"' + str(d).replace('"', '\\"') + '"'


def _toml_dizi(ogeler: list[str]) -> str:
    return "[" + ", ".join(f'"{o}"' for o in ogeler) + "]"


def _atomik_yaz(yol: Path, metin: str) -> None:
    """Gecici dosyaya yaz, sonra yerine koy. Yarim yazilmis dosya birakmaz."""
    gecici = yol.with_name(yol.name + ".yeni")
    gecici.write_text(metin, encoding="utf-8")
    gecici.replace(yol)


def _bolum_araligi(satirlar: list[str], bolum: str) -> tuple[int, int] | None:
    """[bolum] basliginin ve bloğun bittigi yerin indisleri. Yoksa None."""
    hedef = "[" + bolum + "]"
    for i, s in enumerate(satirlar):
        if s.strip() == hedef:
            j = i + 1
            while j < len(satirlar) and not satirlar[j].lstrip().startswith("["):
                j += 1
            return i, j
    return None


def _anahtar_yaz(metin: str, bolum: str, anahtar: str, deger_metni: str) -> str:
    """Bolumdeki anahtari degistirir; bolum ya da anahtar yoksa ekler.

    Dosyanin geri kalanina DOKUNMAZ — yorumlar ve siralama korunur.
    """
    satirlar = metin.splitlines()
    aralik = _bolum_araligi(satirlar, bolum)
    yeni_satir = f"{anahtar} = {deger_metni}"

    if aralik is None:
        if satirlar and satirlar[-1].strip():
            satirlar.append("")
        satirlar += [f"[{bolum}]", yeni_satir, ""]
        return "\n".join(satirlar) + "\n"

    bas, son = aralik
    kalip = re.compile(r"^\s*" + re.escape(anahtar) + r"\s*=")
    for i in range(bas + 1, son):
        if kalip.match(satirlar[i]):
            satirlar[i] = yeni_satir
            return "\n".join(satirlar) + "\n"

    ekle = son
    while ekle - 1 > bas and not satirlar[ekle - 1].strip():
        ekle -= 1
    satirlar.insert(ekle, yeni_satir)
    return "\n".join(satirlar) + "\n"


def _anahtar_sil(metin: str, bolum: str, anahtar: str) -> str:
    """Anahtari siler; bolum bosaldiysa bolumu de siler."""
    satirlar = metin.splitlines()
    aralik = _bolum_araligi(satirlar, bolum)
    if aralik is None:
        return metin
    bas, son = aralik
    kalip = re.compile(r"^\s*" + re.escape(anahtar) + r"\s*=")
    kalan = [s for s in satirlar[bas + 1:son] if not kalip.match(s)]
    if any(s.strip() and not s.lstrip().startswith("#") for s in kalan):
        satirlar[bas + 1:son] = kalan
    else:
        satirlar[bas:son] = []
    return "\n".join(satirlar) + "\n"


def _bolum_sil(metin: str, bolum: str) -> str:
    """[bolum] basligi ve altindaki satirlari siler; geriye dokunmaz."""
    satirlar = metin.splitlines()
    aralik = _bolum_araligi(satirlar, bolum)
    if aralik is None:
        return metin
    bas, son = aralik
    satirlar[bas:son] = []
    return "\n".join(satirlar) + "\n"


def _dizi_araligi(satirlar: list[str], bolum: str, anahtar: str) -> tuple[int, int] | None:
    """TOML dizisinin (baslangic, kapanis) satir indeksleri."""
    aralik = _bolum_araligi(satirlar, bolum)
    if aralik is None:
        return None
    bas, son = aralik
    kalip = re.compile(r"^\s*" + re.escape(anahtar) + r"\s*=\s*\[")
    for i in range(bas + 1, son):
        if kalip.match(satirlar[i]):
            derinlik = 0
            for j in range(i, son):
                govde = satirlar[j].split("#", 1)[0]
                derinlik += govde.count("[") - govde.count("]")
                if derinlik <= 0:
                    return (i, j)
            return None
    return None


def _dizi_oge_ekle(metin: str, bolum: str, anahtar: str, deger: str) -> str | None:
    """Diziye tek satir ekler; dizinin geri kalanina ve YORUMLARA dokunmaz."""
    satirlar = metin.splitlines()
    yer = _dizi_araligi(satirlar, bolum, anahtar)
    if yer is None:
        return None
    bas, kapanis = yer
    if bas == kapanis:
        govde = satirlar[bas]
        kapa = govde.rindex("]")
        ic = govde[govde.index("[") + 1:kapa].strip()
        ayirac = "" if not ic or ic.endswith(",") else ", "
        satirlar[bas] = govde[:kapa] + ayirac + json.dumps(deger) + govde[kapa:]
    else:
        satirlar.insert(kapanis, f"    {json.dumps(deger)},")
    return "\n".join(satirlar) + "\n"


def _dizi_oge_sil(metin: str, bolum: str, anahtar: str, deger: str) -> str | None:
    """Diziden bir ogeyi siler."""
    satirlar = metin.splitlines()
    yer = _dizi_araligi(satirlar, bolum, anahtar)
    if yer is None:
        return None
    bas, kapanis = yer
    hedef = json.dumps(deger)
    if bas == kapanis:
        govde = satirlar[bas]
        ac, kapa = govde.index("["), govde.rindex("]")
        ogeler = [p.strip() for p in govde[ac + 1:kapa].split(",") if p.strip()]
        if hedef not in ogeler:
            return None
        ogeler.remove(hedef)
        satirlar[bas] = govde[:ac + 1] + ", ".join(ogeler) + govde[kapa:]
        return "\n".join(satirlar) + "\n"
    for i in range(bas + 1, kapanis):
        if satirlar[i].split("#", 1)[0].strip().rstrip(",").strip() == hedef:
            del satirlar[i]
            return "\n".join(satirlar) + "\n"
    return None


def _yol_ogelerini_degistir(satirlar: list[str], bas: int, son: int,
                            eski_yol: str, yeni_yol: str) -> list[str]:
    """Bir TOML bolumu icindeki yol ogelerini guvenle gunceller."""
    eski_kalip = re.compile(rf'"{re.escape(eski_yol)}(?:/([^"]*))?"')
    yeni_satirlar = []
    for satir in satirlar[bas:son]:
        def degistir(match: re.Match[str]) -> str:
            kalan = match.group(1)
            if kalan:
                return f'"{yeni_yol}/{kalan}"'
            return f'"{yeni_yol}"'
        yeni_satir = eski_kalip.sub(degistir, satir)
        yeni_satirlar.append(yeni_satir)
    return yeni_satirlar
