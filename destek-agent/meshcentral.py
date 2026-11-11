"""MeshCentral ile konuşan küçük yardımcı modül.

MeshCentral'ın kendi komut satırı aracı olan meshctrl.js'i çağırır:
  - Cihazları listeler
  - Bir cihazda PowerShell / CMD komutu çalıştırıp çıktısını döndürür
"""

import asyncio
import json
import os

KOMUT_ZAMAN_ASIMI = 180  # saniye


def _baglanti_argumanlari() -> list[str]:
    return [
        "--url", os.environ["MESHCENTRAL_URL"],
        "--loginuser", os.environ["MESHCENTRAL_KULLANICI"],
        "--loginpass", os.environ["MESHCENTRAL_SIFRE"],
    ]


async def _meshctrl(*argumanlar: str, zaman_asimi: int = KOMUT_ZAMAN_ASIMI) -> str:
    """meshctrl.js'i çalıştırır ve çıktısını döndürür. Hata olursa RuntimeError fırlatır."""
    surec = await asyncio.create_subprocess_exec(
        "node", os.environ["MESHCTRL_YOLU"], *argumanlar, *_baglanti_argumanlari(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        cikti, hata = await asyncio.wait_for(surec.communicate(), timeout=zaman_asimi)
    except asyncio.TimeoutError:
        surec.kill()
        raise RuntimeError(f"Komut {zaman_asimi} saniye içinde bitmedi (zaman aşımı).")

    cikti_metni = cikti.decode("utf-8", errors="replace").strip()
    hata_metni = hata.decode("utf-8", errors="replace").strip()
    if surec.returncode != 0:
        raise RuntimeError(hata_metni or cikti_metni or f"meshctrl hata kodu {surec.returncode}")
    return cikti_metni


async def cihazlari_listele() -> list[dict]:
    """MeshCentral'daki tüm cihazları sade bir liste olarak döndürür."""
    ham = await _meshctrl("ListDevices", "--json", zaman_asimi=60)
    veri = json.loads(ham) if ham else []

    # meshctrl sürümüne göre liste ya da {grup: [cihazlar]} biçiminde gelebilir
    if isinstance(veri, dict):
        cihazlar = [c for grup in veri.values() if isinstance(grup, list) for c in grup]
    else:
        cihazlar = veri

    sonuc = []
    for c in cihazlar:
        sonuc.append({
            "id": c.get("_id"),
            "ad": c.get("name"),
            "grup": c.get("groupname") or c.get("meshid"),
            "isletim_sistemi": c.get("osdesc"),
            # conn alanının 1. biti = ajan bağlı
            "cevrimici": bool(int(c.get("conn", 0) or 0) & 1),
        })
    return sonuc


async def komut_calistir(cihaz_id: str, komut: str, powershell: bool = True) -> str:
    """Cihazda komut çalıştırır ve çıktısını döndürür."""
    argumanlar = ["RunCommand", "--id", cihaz_id, "--run", komut, "--reply"]
    if powershell:
        argumanlar.append("--powershell")
    cikti = await _meshctrl(*argumanlar)
    return cikti or "(komut çalıştı, çıktı üretmedi)"
