"""anlamsal.py — Yerel Ollama embedding ile anlamsal arama (Notlar ve Çalışma Alanı).

Gizlilik garantisi: Embedding istekleri YALNIZCA yerel geri döngü adreslerine
(127.0.0.1, localhost, ::1) gönderilir; sistem vekil sunucuları (proxy) devre
dışıdır (trust_env=False). Veri hiçbir koşulda bilgisayardan dışarı çıkmaz.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
from pathlib import Path
from urllib.parse import urlparse

import httpx

from pevrai import journal
from pevrai.ceviri import t

VARSAYILAN_OLLAMA_URL = "http://127.0.0.1:11434"
TERCIH_MODELLER = (
    "nomic-embed-text",
    "bge-m3",
    "mxbai-embed-large",
    "all-minilm",
    "snowflake-arctic-embed",
    "multilingual-e5",
)
_KILIT = threading.RLock()


def yerel_adres_dogrula(url: str = "") -> str:
    """URL'nin yalnızca yerel makineye (loopback) işaret ettiğini doğrular."""
    aday = (url or os.environ.get("PEVRAI_OLLAMA_URL") or VARSAYILAN_OLLAMA_URL).strip().rstrip("/")
    parsed = urlparse(aday)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(t("Anlamsal arama yalnızca yerel Ollama (127.0.0.1 / localhost) ile çalışır; veri bilgisayardan çıkarılamaz."))
    return aday


def kosinus(a: list[float], b: list[float]) -> float:
    """İki vektör arasındaki kosinüs benzerliğini hesaplar."""
    if not a or not b or len(a) != len(b):
        return 0.0
    ic = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    return ic / (na * nb)


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(float(x) * float(x) for x in v))
    if n <= 1e-12:
        return [0.0 for _ in v]
    return [round(float(x) / n, 6) for x in v]


def _model_sec(istemci: httpx.Client, model: str = "") -> str:
    secim = (model or os.environ.get("PEVRAI_EMBED_MODEL") or "").strip()
    if secim:
        return secim
    try:
        r = istemci.get("/api/tags")
        if r.status_code == 200:
            modeller = [str(m.get("name", "")) for m in (r.json().get("models") or []) if m.get("name")]
            for tercih in TERCIH_MODELLER:
                for m in modeller:
                    if m == tercih or m.startswith(tercih + ":"):
                        return m
            if modeller:
                return modeller[0]
    except Exception:
        pass
    return "nomic-embed-text"


def gomme_uret(metinler: list[str], model: str = "", taban_url: str = "", zaman_asimi: float = 8.0) -> list[list[float]]:
    """Yerel Ollama üzerinden verilen metinlerin birim-uzunluklu embedding vektörlerini üretir."""
    if not metinler:
        return []
    taban = yerel_adres_dogrula(taban_url)
    temiz = [str(m or "")[:6000] for m in metinler]
    with httpx.Client(base_url=taban, timeout=zaman_asimi, trust_env=False) as istemci:
        secilen_model = _model_sec(istemci, model)
        try:
            r = istemci.post("/api/embed", json={"model": secilen_model, "input": temiz})
            if r.status_code == 200:
                vektorler = r.json().get("embeddings") or []
                if len(vektorler) == len(temiz):
                    return [_norm(v) for v in vektorler]
        except httpx.HTTPError as e:
            raise ValueError(t("Yerel Ollama bağlantı hatası: {hata}", hata=e)) from e

        # Eski Ollama sürümleri için /api/embeddings yedeği
        sonuclar: list[list[float]] = []
        for metin in temiz:
            try:
                r = istemci.post("/api/embeddings", json={"model": secilen_model, "prompt": metin})
            except httpx.HTTPError as e:
                raise ValueError(t("Yerel Ollama bağlantı hatası: {hata}", hata=e)) from e
            if r.status_code != 200:
                raise ValueError(t("Yerel Ollama embedding üretemedi (HTTP {kod}).", kod=r.status_code))
            emb = r.json().get("embedding") or []
            if not emb:
                raise ValueError(t("Yerel Ollama boş embedding döndürdü."))
            sonuclar.append(_norm(emb))
        return sonuclar


def _onbellek_yolu() -> Path:
    return journal.KOK / "anlamsal_onbellek.sqlite3"


def onbellekli_gommeler(metinler: list[str], model: str = "", taban_url: str = "") -> list[list[float]]:
    """Metinlerin embedding vektörlerini yerel SQLite önbelleğini kullanarak döndürür."""
    if not metinler:
        return []
    taban = yerel_adres_dogrula(taban_url)
    anahtar_model = (model or os.environ.get("PEVRAI_EMBED_MODEL") or "varsayilan").strip()
    anahtarlar = [
        hashlib.sha256((anahtar_model + "\0" + str(m or "")[:6000]).encode("utf-8", errors="replace")).hexdigest()
        for m in metinler
    ]
    bulunan: dict[str, list[float]] = {}
    yol = _onbellek_yolu()
    from contextlib import closing
    with _KILIT:
        yol.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(yol, timeout=10)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS embeddings (sha TEXT PRIMARY KEY, vector TEXT NOT NULL)")
            for k in set(anahtarlar):
                row = db.execute("SELECT vector FROM embeddings WHERE sha=?", (k,)).fetchone()
                if row:
                    try:
                        bulunan[k] = json.loads(row[0])
                    except ValueError:
                        pass

    eksik_indeksler = [i for i, k in enumerate(anahtarlar) if k not in bulunan]
    if eksik_indeksler:
        eksik_metinler = [metinler[i] for i in eksik_indeksler]
        yeni_vektorler = gomme_uret(eksik_metinler, model=model, taban_url=taban)
        with _KILIT:
            with closing(sqlite3.connect(yol, timeout=10)) as db, db:
                db.execute("CREATE TABLE IF NOT EXISTS embeddings (sha TEXT PRIMARY KEY, vector TEXT NOT NULL)")
                for idx, vek in zip(eksik_indeksler, yeni_vektorler):
                    k = anahtarlar[idx]
                    bulunan[k] = vek
                    db.execute("INSERT OR REPLACE INTO embeddings VALUES(?,?)", (k, json.dumps(vek)))
                # Önbellek boyutunu en fazla 10.000 kayıtla sınırla
                db.execute(
                    "DELETE FROM embeddings WHERE rowid NOT IN (SELECT rowid FROM embeddings ORDER BY rowid DESC LIMIT 10000)"
                )
    return [bulunan[k] for k in anahtarlar]


def metinleri_sirala(
    sorgu: str,
    ogeler: list[dict],
    metin_anahtari: str = "metin",
    limit: int = 20,
    esik: float = 0.15,
    model: str = "",
    taban_url: str = "",
) -> list[dict]:
    """Öğeleri sorguya olan anlamsal (kosinüs) benzerliğine göre azalan sırada döndürür."""
    sorgu_temiz = (sorgu or "").strip()
    if not sorgu_temiz or not ogeler:
        return []
    metinler = [sorgu_temiz] + [str(o.get(metin_anahtari, "")) for o in ogeler]
    vektorler = onbellekli_gommeler(metinler, model=model, taban_url=taban_url)
    sorgu_v = vektorler[0]
    puanli = []
    for oge, vek in zip(ogeler, vektorler[1:]):
        skor = kosinus(sorgu_v, vek)
        if skor >= esik:
            kopya = dict(oge)
            kopya["score"] = round(skor, 4)
            puanli.append(kopya)
    puanli.sort(key=lambda x: x["score"], reverse=True)
    return puanli[: max(1, int(limit))]
