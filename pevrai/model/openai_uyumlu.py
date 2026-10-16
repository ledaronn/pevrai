"""model/openai_uyumlu.py — OpenAI Chat Completions bicimini konusan her sunucu.

Tek adaptor: OpenAI, OpenRouter, Groq, Together, Ollama (http://localhost:11434/v1),
LM Studio (http://localhost:1234/v1), vLLM... taban_url ile secilir. Ek SDK yok,
httpx zaten bagimlilik.
"""
from __future__ import annotations

import json
from typing import Any, Iterator

import httpx

from pevrai.model.taban import (AracCagrisi, ModelHatasi, OranSiniri, Saglayici, kimlikleri_tamamla,
                                arac_adi_coz, arac_adi_kodla,
                                SunucuHatasi, Yanit, ZamanAsimi, model_turu,
                                yeni_cagri_kimligi)

VARSAYILAN_TABAN = "https://api.openai.com/v1"


class OpenAIUyumlu(Saglayici):
    ad = "openai"

    def __init__(self, anahtar: str, zaman_asimi_sn: float, taban_url: str = "") -> None:
        self._taban = (taban_url or VARSAYILAN_TABAN).rstrip("/")
        basliklar = {"Content-Type": "application/json"}
        if anahtar:                     # Ollama gibi yerel sunucularda anahtar olmayabilir
            basliklar["Authorization"] = f"Bearer {anahtar}"
        self._http = httpx.Client(base_url=self._taban, headers=basliklar, timeout=zaman_asimi_sn)

    # --- bicim cevirileri -------------------------------------------------
    @staticmethod
    def _mesajlar(gecmis: list[dict], sistem: str) -> list[dict]:
        cikti: list[dict] = [{"role": "system", "content": sistem}] if sistem else []
        for m in kimlikleri_tamamla(gecmis):
            parcalar = m.get("parcalar", [])
            if m.get("rol") == "model":
                metin = "".join(p.get("metin", "") for p in parcalar if p.get("tip") == "metin")
                cagrilar = [{"id": p.get("id") or yeni_cagri_kimligi(), "type": "function",
                             "function": {"name": arac_adi_kodla(p.get("ad", "")),
                                          "arguments": json.dumps(p.get("args") or {}, ensure_ascii=False)}}
                            for p in parcalar if p.get("tip") == "cagri"]
                mesaj: dict[str, Any] = {"role": "assistant", "content": metin or None}
                if cagrilar:
                    mesaj["tool_calls"] = cagrilar
                cikti.append(mesaj)
                continue
            # user turu: metinler tek mesaj, her sonuc ayri "tool" mesaji
            metin = "".join(p.get("metin", "") for p in parcalar if p.get("tip") == "metin")
            if metin:
                cikti.append({"role": "user", "content": metin})
            for p in parcalar:
                if p.get("tip") == "sonuc":
                    cevap = p.get("cevap") or {}
                    icerik = cevap.get("result") if isinstance(cevap, dict) and "result" in cevap else json.dumps(cevap, ensure_ascii=False)
                    cikti.append({"role": "tool", "tool_call_id": p.get("id") or "", "content": str(icerik)})
        return cikti

    @staticmethod
    def _araclar(araclar: list[dict]) -> list[dict]:
        return [{"type": "function", "function": {
                    "name": arac_adi_kodla(a["name"]), "description": a.get("description", ""),
                    "parameters": a.get("parameters") or {"type": "object", "properties": {}}}}
                for a in araclar]

    # --- sozlesme -------------------------------------------------------
    def uret(self, model: str, gecmis: list[dict], sistem: str,
             araclar: list[dict] | None, zorla_arac: str | None = None) -> Yanit:
        govde: dict[str, Any] = {"model": model, "messages": self._mesajlar(gecmis, sistem)}
        if araclar is not None:
            govde["tools"] = self._araclar(araclar)
            if zorla_arac:
                govde["tool_choice"] = {"type": "function", "function": {"name": arac_adi_kodla(zorla_arac)}}
        try:
            r = self._http.post("/chat/completions", json=govde)
        except httpx.TimeoutException as e:
            raise ZamanAsimi(str(e)) from e
        except httpx.HTTPError as e:
            raise ModelHatasi(0, f"baglanti hatasi: {e}") from e
        if r.status_code == 429:
            raise OranSiniri(429, _hata_metni(r))
        if r.status_code >= 500:
            raise SunucuHatasi(r.status_code, _hata_metni(r))
        if r.status_code >= 400:
            raise ModelHatasi(r.status_code, _hata_metni(r))

        veri = r.json()
        secim = (veri.get("choices") or [{}])[0].get("message") or {}
        metin = secim.get("content") or None
        cagrilar = []
        for tc in secim.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {"_ham": fn.get("arguments")}
            cagrilar.append(AracCagrisi(ad=arac_adi_coz(fn.get("name", "")), args=args if isinstance(args, dict) else {},
                                        id=tc.get("id") or yeni_cagri_kimligi()))
        k = veri.get("usage") or {}
        return Yanit(metin=metin, cagrilar=cagrilar, icerik=model_turu(metin, cagrilar),
                     girdi_token=int(k.get("prompt_tokens") or 0),
                     cikti_token=int(k.get("completion_tokens") or 0))

    def uret_akis(self, model: str, gecmis: list[dict], sistem: str,
                  araclar: list[dict] | None, zorla_arac: str | None = None) -> Iterator[str | Yanit]:
        govde: dict[str, Any] = {
            "model": model,
            "messages": self._mesajlar(gecmis, sistem),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if araclar is not None:
            govde["tools"] = self._araclar(araclar)
            if zorla_arac:
                govde["tool_choice"] = {"type": "function", "function": {"name": arac_adi_kodla(zorla_arac)}}

        metin_parcalari: list[str] = []
        cagrilar_ham: dict[int, dict[str, Any]] = {}
        girdi_token = 0
        cikti_token = 0

        try:
            with self._http.stream("POST", "/chat/completions", json=govde) as r:
                if r.status_code == 429:
                    r.read()
                    raise OranSiniri(429, _hata_metni(r))
                if r.status_code >= 500:
                    r.read()
                    raise SunucuHatasi(r.status_code, _hata_metni(r))
                if r.status_code >= 400:
                    r.read()
                    raise ModelHatasi(r.status_code, _hata_metni(r))

                ct = r.headers.get("content-type", "").lower()
                if "text/event-stream" not in ct:
                    ham = r.read().decode("utf-8", errors="replace")
                    try:
                        veri = json.loads(ham)
                    except ValueError:
                        veri = {}
                    secim = (veri.get("choices") or [{}])[0].get("message") or {}
                    metin = secim.get("content") or None
                    cagrilar = []
                    for tc in secim.get("tool_calls") or []:
                        fn = tc.get("function") or {}
                        try:
                            args = json.loads(fn.get("arguments") or "{}")
                        except ValueError:
                            args = {"_ham": fn.get("arguments")}
                        cagrilar.append(AracCagrisi(ad=arac_adi_coz(fn.get("name", "")),
                                                    args=args if isinstance(args, dict) else {},
                                                    id=tc.get("id") or yeni_cagri_kimligi()))
                    k = veri.get("usage") or {}
                    yn = Yanit(metin=metin, cagrilar=cagrilar, icerik=model_turu(metin, cagrilar),
                               girdi_token=int(k.get("prompt_tokens") or 0),
                               cikti_token=int(k.get("completion_tokens") or 0))
                    if metin:
                        yield metin
                    yield yn
                    return

                for satir in r.iter_lines():
                    satir = satir.strip()
                    if not satir or not satir.startswith("data:"):
                        continue
                    ham = satir[5:].strip()
                    if ham == "[DONE]":
                        break
                    try:
                        veri = json.loads(ham)
                    except ValueError:
                        continue

                    k = veri.get("usage")
                    if k:
                        girdi_token = int(k.get("prompt_tokens") or girdi_token)
                        cikti_token = int(k.get("completion_tokens") or cikti_token)

                    secimler = veri.get("choices") or []
                    if not secimler:
                        continue
                    delta = secimler[0].get("delta") or {}

                    icerik = delta.get("content")
                    if icerik:
                        metin_parcalari.append(icerik)
                        yield icerik

                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        if idx not in cagrilar_ham:
                            cagrilar_ham[idx] = {
                                "id": tc.get("id") or "",
                                "name": "",
                                "arguments": ""
                            }
                        if tc.get("id"):
                            cagrilar_ham[idx]["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            cagrilar_ham[idx]["name"] += fn["name"]
                        if fn.get("arguments"):
                            cagrilar_ham[idx]["arguments"] += fn["arguments"]

        except httpx.TimeoutException as e:
            raise ZamanAsimi(str(e)) from e
        except httpx.HTTPError as e:
            raise ModelHatasi(0, f"baglanti hatasi: {e}") from e

        metin = "".join(metin_parcalari) or None
        cagrilar = []
        for idx in sorted(cagrilar_ham.keys()):
            item = cagrilar_ham[idx]
            ham_args = item.get("arguments", "{}")
            try:
                args = json.loads(ham_args) if ham_args else {}
            except ValueError:
                args = {"_ham": ham_args}
            cagrilar.append(AracCagrisi(
                ad=arac_adi_coz(item.get("name", "")),
                args=args if isinstance(args, dict) else {},
                id=item.get("id") or yeni_cagri_kimligi()
            ))

        if not girdi_token and not cikti_token and metin:
            cikti_token = max(1, len(metin) // 4)

        yanit = Yanit(
            metin=metin,
            cagrilar=cagrilar,
            icerik=model_turu(metin, cagrilar),
            girdi_token=girdi_token,
            cikti_token=cikti_token
        )
        yield yanit

    def modeller(self) -> list[str]:
        r = self._http.get("/models")
        if r.status_code >= 400:
            raise ModelHatasi(r.status_code, _hata_metni(r))
        return sorted(str(m.get("id")) for m in (r.json().get("data") or []) if m.get("id"))


def _hata_metni(r: httpx.Response) -> str:
    try:
        veri = r.json()
        hata = veri.get("error") if isinstance(veri, dict) else None
        if isinstance(hata, dict) and hata.get("message"):
            return str(hata["message"])
        if isinstance(hata, str):
            return hata
    except ValueError:
        pass
    return (r.text or r.reason_phrase or "")[:300]
