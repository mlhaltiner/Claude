"""Hangi komutların onaysız çalışabileceğine karar veren kurallar.

Kural basit ve temkinli: Komut yalnızca bilgi okuyan komutlardan oluşuyorsa
onaysız çalışabilir. Şüpheli olan her şey Telegram onayına gider.
"""

import re

# Bilgi okuyan, sistemi değiştirmeyen komutlar (küçük harfle)
OKUMA_KOMUTLARI = {
    "ipconfig", "ping", "tracert", "nslookup", "hostname", "whoami", "systeminfo",
    "tasklist", "netstat", "getmac", "ver", "driverquery",
    "select-object", "select", "format-list", "fl", "format-table", "ft",
    "where-object", "where", "?", "sort-object", "sort", "measure-object",
    "out-string", "convertto-json", "group-object",
}

# PowerShell'de bu fiillerle başlayan komutlar okuma amaçlıdır
OKUMA_FIILLERI = ("get-", "test-", "resolve-", "measure-", "find-")

# Komut zinciri, yönlendirme veya alt komut gibi tehlikeli olabilecek işaretler
SUPHELI_ISARETLER = re.compile(r"[;&>`]|\$\(|\|\|")

# Okuma fiiliyle başlasa da riskli kabul ettiğimiz kelimeler
YASAKLI_KELIMELER = re.compile(
    r"invoke-expression|\biex\b|-computername|start-process|remove-|set-|stop-|"
    r"restart-|new-|add-|clear-|disable-|enable-|uninstall|format-volume|-encodedcommand",
    re.IGNORECASE,
)


def salt_okuma_mi(komut: str) -> bool:
    """Komut sadece bilgi okuyorsa True, aksi halde False döndürür."""
    if SUPHELI_ISARETLER.search(komut) or YASAKLI_KELIMELER.search(komut):
        return False

    for parca in komut.split("|"):
        kelimeler = parca.strip().split()
        if not kelimeler:
            return False
        ilk = kelimeler[0].lower()
        if ilk in OKUMA_KOMUTLARI or ilk.startswith(OKUMA_FIILLERI):
            continue
        return False
    return True
