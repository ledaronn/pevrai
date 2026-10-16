# baslat.py — tek giris noktasi: pencere, MCP alt sureci ya da tanilama.
#
#   python -m pevrai                     -> pencere (pencere.main)
#   Pevrai.exe                           -> pencere
#   Pevrai.exe --mcp-sunucu <betik.py>   -> betigi stdio MCP sunucusu olarak kosar
#   Pevrai.exe --tani                    -> ortam tanilamasi (metin), pencere acmaz
#   Pevrai.exe --tani-ayrintili           -> yalniz yerel kullanim icin yollar/hata ayrintilari
#   Pevrai.exe --isci <tarif.json>       -> ekip iscisi (dar politika, ayri surec; bkz. ekip.py)
#
# NEDEN AYRI DOSYA: pencere.py modul duzeyinde webview'i (WinForms/CLR) ice
# aktarir. MCP alt sureci icin o yuku odemek istemiyoruz — ve bir stdio
# sunucusunun stdout'una pencere kodunun tek satir bile yazmasi protokolu
# bozar. Bu yuzden argv burada, hicbir agir modul yuklenmeden okunur.
#
# DONDURULMUS SURUMDE python.exe yok: policy.toml'daki
# komut = ["python", "Donusturucu/server.py"] satiri mcp_bridge.komut_cozumle
# ile [Pevrai.exe, --mcp-sunucu, <tam yol>] olur ve buraya duser. Betik ayni
# surecte, kendi klasoru sys.path'e eklenerek (core_engine gibi yan
# modulleri bulsun) __main__ olarak calisir.
from __future__ import annotations

import runpy
import sys
from pathlib import Path


def _mcp_sunucu(betik: str) -> int:
    yol = Path(betik).resolve()
    if not yol.is_file():
        sys.stderr.write(f"MCP betigi yok: {yol}\n")
        return 2
    sys.path.insert(0, str(yol.parent))
    sys.argv = [str(yol)]
    runpy.run_path(str(yol), run_name="__main__")
    return 0


def tanila(*, ayrintili: bool = False) -> str:
    """Kurulumun durumu, tek bakista. Kullanici 'acilmiyor' dediginde ilk
    istenen sey; --tani yolları ve ham hata metinlerini gizler. Anahtar
    YAZILMAZ, yalnizca kaynagi (ortam/keyring/dosya/yok). Ayrıntılı çıktı
    açıkça istendiğinde yolları/hata metinlerini yerel inceleme için gösterir."""
    import platform
    from pevrai import DONMUS, KAYNAK_KOK, PAKET, PROJE_KOKU
    from pevrai.ceviri import t
    def hata(e: Exception) -> str:
        return f"{type(e).__name__}: {e}" if ayrintili else type(e).__name__
    gizli = t("gizli (paylaşılabilir tanı)")
    satirlar = [
        f"Pevrai {surum()}",
        f"Python  : {platform.python_version()} ({'dondurulmus .exe' if DONMUS else 'kaynaktan'})",
        f"Sistem  : {platform.platform()}",
        f"Kod     : {PAKET if ayrintili else gizli}",
        f"Kaynak  : {KAYNAK_KOK if ayrintili else gizli}",
        f"Veri    : {PROJE_KOKU if ayrintili else gizli}",
    ]
    if ayrintili:
        satirlar.insert(1, t("Ayrıntılı tanı kişisel yollar ve hata ayrıntıları içerebilir; yalnızca yerelde kullanın."))
    for ad in ("policy.toml", "config/persona.md", "config/arayuz.toml"):
        satirlar.append(f"  {ad:20} {'var' if (PROJE_KOKU / ad).exists() else 'yok (ilk acilista sablondan)'}")
    try:
        from pevrai import anahtar
        for s in ("gemini", "openai", "anthropic"):
            try:
                kaynak = anahtar.kaynak(s)
                if not ayrintili and kaynak not in ("keyring", "dosya", "ortam", "yok"):
                    kaynak = t("bilinmeyen anahtar kaynağı")
            except Exception as e:
                kaynak = f"okunamadi ({hata(e)})"
            satirlar.append(f"Anahtar {s:10}: {kaynak}")
    except Exception as e:
        satirlar.append(f"Anahtar: okunamadi ({hata(e)})")
    import importlib.util
    for paket, ne in (("mcp", "MCP (zorunlu)"), ("httpx", "HTTP (zorunlu)"), ("webview", "pencere (zorunlu)"),
                      ("google.genai", "Gemini"), ("anthropic", "Anthropic"), ("keyring", "anahtar deposu"),
                      ("playwright", "tarayici"), ("pymupdf", "PDF"), ("docx", "DOCX"), ("pptx", "PPTX"),
                      ("openpyxl", "XLSX")):
        try:
            durum = 'var' if importlib.util.find_spec(paket) else 'yok'
        except (ImportError, ValueError):
            # Optional namespace parents may be missing, or have no __spec__.
            durum = 'yok'
        except Exception as e:
            durum = f"hata: {hata(e)}"
        satirlar.append(f"  {ne:18} {durum}")
    try:
        from pevrai import ocr
        neden = ocr.kullanilamaz_nedeni()
        durum = 'var' if neden is None else 'yok'
        if ayrintili:
            durum = 'var, diller: ' + ', '.join(ocr.diller()) if neden is None else 'yok — ' + neden
        satirlar.append(f"  {'OCR':18} {durum}")
    except Exception as e:
        satirlar.append(f"  {'OCR':18} hata: {hata(e)}")
    if not ayrintili:
        satirlar.append(t("Bu tanı yolları ve hata ayrıntılarını gizler. Ayrıntılı yerel çıktı: --tani-ayrintili."))
    return "\n".join(satirlar)


def surum() -> str:
    from pevrai import DONMUS, KAYNAK_KOK
    # Editable metadata can be stale after changing the source version.
    if not DONMUS:
        try:
            import tomllib
            with (KAYNAK_KOK / "pyproject.toml").open("rb") as f:
                return str(tomllib.load(f)["project"]["version"])
        except (OSError, KeyError, ValueError):
            pass
    try:
        from importlib.metadata import version
        return version("pevrai")
    except Exception:
        return "(surum bilgisi yok)"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--mcp-sunucu"]:
        if len(argv) < 2:
            sys.stderr.write("Kullanim: --mcp-sunucu <betik.py>\n")
            return 2
        return _mcp_sunucu(argv[1])
    if argv[:1] == ["--isci"]:
        # Ekip iscisi: dar politikayla tek alt gorev (ekip.isci_calistir).
        if len(argv) < 2:
            sys.stderr.write("Kullanim: --isci <tarif.json>\n")
            return 2
        from pevrai.ekip import isci_calistir
        return isci_calistir(argv[1])
    if argv[:1] in (["--tani"], ["--tani-ayrintili"], ["--surum"], ["--version"]):
        print(tanila(ayrintili=argv[0] == "--tani-ayrintili") if argv[0].startswith("--tani") else surum())
        return 0
    from pevrai.pencere import main as pencere_main
    return pencere_main()


if __name__ == "__main__":
    sys.exit(main())
