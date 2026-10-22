"""Araç çıktısı metin kalır; yürütme durumu izin kararından bağımsızdır."""
from __future__ import annotations


class AracSonucu(str):
    basarili: bool
    ek: dict | None

    def __new__(cls, metin: str, basarili: bool = True, ek: dict | None = None):
        sonuc = super().__new__(cls, metin)
        sonuc.basarili = basarili
        sonuc.ek = ek
        return sonuc


def hata(metin: str, ek: dict | None = None) -> AracSonucu:
    return AracSonucu(metin, False, ek)
