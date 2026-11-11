"""Telegram üzerinden çalışan BT destek agent'ı.

Siz Telegram'dan sorunu yazarsınız, Claude:
  1. MeshCentral'daki cihazları bulur,
  2. Teşhis için komut çalıştırır (bilgi okuyan komutlar onaysız),
  3. Değişiklik yapan her komut için size Telegram'dan onay sorar,
  4. Sonucu raporlar.

Çalıştırma:  python bot.py
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import meshcentral
from guvenlik import salt_okuma_mi

load_dotenv()

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("destek-agent")

MODEL = "claude-opus-5-5"
MAKS_ADIM = 25            # bir sorunda en fazla kaç araç çağrısı yapılabilir
MAKS_CIKTI = 15000        # komut çıktısının Claude'a gönderilecek en fazla karakteri
ONAY_ZAMAN_ASIMI = 600    # onay için en fazla bekleme süresi (saniye)

IZINLI_KULLANICILAR = {
    int(x) for x in os.environ.get("IZINLI_KULLANICILAR", "").replace(" ", "").split(",") if x
}
OKUMA_ONAYSIZ = os.environ.get("OKUMA_KOMUTLARI_ONAYSIZ", "true").lower() == "true"

LOG_KLASORU = Path(__file__).parent / "loglar"
LOG_KLASORU.mkdir(exist_ok=True)

client = anthropic.AsyncAnthropic()

SISTEM_TALIMATI = """Sen bir bilgisayar danışmanlık şirketinin uzaktan BT destek uzmanısın.
Teknisyen sana Telegram'dan müşteri sorunlarını Türkçe yazar. Müşteri bilgisayarlarına
MeshCentral üzerinden erişirsin ve araçlarınla komut çalıştırabilirsin.

Çalışma şeklin:
1. Önce `cihazlari_listele` ile hangi cihazdan bahsedildiğini bul. Emin değilsen teknisyene sor.
2. Teşhis için önce yalnızca bilgi okuyan komutlar çalıştır (Get-Service, Get-Printer,
   Get-EventLog, ipconfig, Test-NetConnection vb.). Sorunun nedenini kanıtla bul.
3. Düzeltme gerekiyorsa en küçük, geri alınabilir değişikliği seç. Değişiklik yapan her komut
   teknisyenin onayına gider; `aciklama` alanında ne yapacağını ve neden yapacağını sade Türkçe ile yaz.
4. Düzeltmeden sonra sorunun gerçekten çözüldüğünü bir okuma komutuyla doğrula.
5. Sonunda kısa bir rapor ver: sorun neydi, ne yaptın, şu an durum ne, müşteriye ne söylenmeli.

Kurallar:
- Komutlar Windows PowerShell'de SYSTEM yetkisiyle çalışır; etkileşimli (soru soran) komut kullanma.
- Dosya silme, disk biçimlendirme, kullanıcı/şifre değiştirme, güvenlik yazılımını kapatma gibi
  ciddi işlemleri, teknisyen açıkça istemedikçe önerme.
- Teknisyen bir komutu reddederse ısrar etme; başka bir yol öner ya da elle yapılacak adımları anlat.
- Ekrandan (arayüzden) yapılması gereken işler için teknisyene adım adım talimat ver.
- Yanıtlarını Telegram'da okunacağı için kısa tut, uzun tablolar kullanma."""

ARACLAR = [
    {
        "name": "cihazlari_listele",
        "description": "MeshCentral'a kayıtlı tüm müşteri bilgisayarlarını listeler: id, ad, grup, "
                       "işletim sistemi ve çevrimiçi olup olmadığı.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "komut_calistir",
        "description": "Bir müşteri bilgisayarında komut çalıştırır ve çıktısını döndürür. "
                       "Sadece bilgi okuyan komutlar hemen çalışabilir; sistemi değiştiren komutlar "
                       "teknisyenin Telegram onayından sonra çalışır. Teknisyen reddederse "
                       "'REDDEDİLDİ' döner.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cihaz_id": {"type": "string", "description": "cihazlari_listele'den gelen id"},
                "komut": {"type": "string", "description": "Çalıştırılacak komut"},
                "powershell": {"type": "boolean", "description": "true: PowerShell, false: CMD"},
                "aciklama": {
                    "type": "string",
                    "description": "Teknisyene gösterilecek, komutun ne yapacağını anlatan kısa Türkçe açıklama",
                },
            },
            "required": ["cihaz_id", "komut", "powershell", "aciklama"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]

# Sohbet geçmişi (chat_id -> mesajlar) ve bekleyen onaylar (onay_id -> Future)
sohbetler: dict[int, list] = {}
bekleyen_onaylar: dict[str, asyncio.Future] = {}
calisan_sohbetler: set[int] = set()


def islem_kaydet(chat_id: int, olay: str, veri: dict) -> None:
    """Her işlemi günlük log dosyasına yazar (müşteriye rapor için)."""
    dosya = LOG_KLASORU / f"{datetime.now():%Y-%m-%d}.jsonl"
    kayit = {"zaman": datetime.now().isoformat(timespec="seconds"), "chat": chat_id, "olay": olay, **veri}
    with dosya.open("a", encoding="utf-8") as f:
        f.write(json.dumps(kayit, ensure_ascii=False) + "\n")


async def mesaj_gonder(context: ContextTypes.DEFAULT_TYPE, chat_id: int, metin: str, **kwargs) -> None:
    """Telegram'ın 4096 karakter sınırına göre mesajı parçalayıp gönderir."""
    for i in range(0, len(metin), 4000):
        await context.bot.send_message(chat_id, metin[i:i + 4000], **kwargs)


async def onay_iste(context, chat_id: int, cihaz_id: str, komut: str, aciklama: str) -> bool:
    onay_id = uuid.uuid4().hex[:12]
    gelecek = asyncio.get_running_loop().create_future()
    bekleyen_onaylar[onay_id] = gelecek

    klavye = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Onayla", callback_data=f"onay:{onay_id}:evet"),
        InlineKeyboardButton("❌ Reddet", callback_data=f"onay:{onay_id}:hayir"),
    ]])
    await context.bot.send_message(
        chat_id,
        f"⚠️ ONAY GEREKİYOR\n\n{aciklama}\n\nCihaz: {cihaz_id}\nKomut:\n{komut}",
        reply_markup=klavye,
    )
    try:
        return await asyncio.wait_for(gelecek, timeout=ONAY_ZAMAN_ASIMI)
    except asyncio.TimeoutError:
        await context.bot.send_message(chat_id, "⏱ Onay süresi doldu, komut çalıştırılmadı.")
        return False
    finally:
        bekleyen_onaylar.pop(onay_id, None)


async def araci_calistir(context, chat_id: int, ad: str, girdi: dict) -> tuple[str, bool]:
    """Bir aracı çalıştırır. (sonuç_metni, hata_mı) döndürür."""
    try:
        if ad == "cihazlari_listele":
            cihazlar = await meshcentral.cihazlari_listele()
            return json.dumps(cihazlar, ensure_ascii=False), False

        if ad == "komut_calistir":
            cihaz_id, komut = girdi["cihaz_id"], girdi["komut"]
            okuma = salt_okuma_mi(komut)
            if not (OKUMA_ONAYSIZ and okuma):
                onaylandi = await onay_iste(context, chat_id, cihaz_id, komut, girdi["aciklama"])
                islem_kaydet(chat_id, "onay", {"cihaz": cihaz_id, "komut": komut, "onaylandi": onaylandi})
                if not onaylandi:
                    return "REDDEDİLDİ: Teknisyen bu komutun çalıştırılmasını onaylamadı.", False
            else:
                await context.bot.send_message(chat_id, f"🔎 {girdi['aciklama']}\n{komut}")

            cikti = await meshcentral.komut_calistir(cihaz_id, komut, girdi["powershell"])
            islem_kaydet(chat_id, "komut", {"cihaz": cihaz_id, "komut": komut, "cikti": cikti[:2000]})
            if len(cikti) > MAKS_CIKTI:
                cikti = cikti[:MAKS_CIKTI] + f"\n...[çıktı kısaltıldı, toplam {len(cikti)} karakter]"
            return cikti, False

        return f"Bilinmeyen araç: {ad}", True
    except Exception as e:  # MeshCentral / ağ hatalarını Claude'a bildir, o da teknisyene açıklasın
        log.exception("Araç hatası")
        return f"HATA: {e}", True


async def agent_calistir(context, chat_id: int, kullanici_mesaji: str) -> None:
    mesajlar = sohbetler.setdefault(chat_id, [])
    mesajlar.append({"role": "user", "content": kullanici_mesaji})
    islem_kaydet(chat_id, "istek", {"mesaj": kullanici_mesaji})

    for _ in range(MAKS_ADIM):
        await context.bot.send_chat_action(chat_id, "typing")
        yanit = await client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SISTEM_TALIMATI,
            tools=ARACLAR,
            messages=mesajlar,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        mesajlar.append({"role": "assistant", "content": yanit.content})

        for blok in yanit.content:
            if blok.type == "text" and blok.text.strip():
                await mesaj_gonder(context, chat_id, blok.text)

        if yanit.stop_reason == "refusal":
            await mesaj_gonder(context, chat_id, "Bu isteği işleyemedim. Lütfen farklı şekilde ifade edin.")
            return
        if yanit.stop_reason == "pause_turn":
            continue
        if yanit.stop_reason != "tool_use":
            islem_kaydet(chat_id, "bitti", {"durum": yanit.stop_reason})
            return

        sonuclar = []
        for blok in yanit.content:
            if blok.type == "tool_use":
                metin, hata = await araci_calistir(context, chat_id, blok.name, blok.input)
                sonuclar.append({
                    "type": "tool_result", "tool_use_id": blok.id, "content": metin, "is_error": hata,
                })
        mesajlar.append({"role": "user", "content": sonuclar})

    await mesaj_gonder(context, chat_id,
                       f"⛔ {MAKS_ADIM} adım sınırına ulaşıldı. Devam etmek için 'devam et' yazın.")


# ---------- Telegram işleyicileri ----------

def yetkili_mi(update: Update) -> bool:
    return update.effective_user is not None and update.effective_user.id in IZINLI_KULLANICILAR


async def mesaj_geldi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not yetkili_mi(update):
        log.warning("Yetkisiz kullanıcı: %s", update.effective_user.id if update.effective_user else "?")
        await update.message.reply_text("Bu botu kullanma yetkiniz yok.")
        return

    chat_id = update.effective_chat.id
    if chat_id in calisan_sohbetler:
        await update.message.reply_text("Önceki iş hâlâ devam ediyor, lütfen bitmesini bekleyin.")
        return

    calisan_sohbetler.add(chat_id)
    try:
        await agent_calistir(context, chat_id, update.message.text)
    except anthropic.APIError as e:
        log.exception("Claude API hatası")
        # Yarım kalan araç çağrısı geçmişi bozmasın diye sohbeti sıfırla
        sohbetler.pop(chat_id, None)
        await update.message.reply_text(f"Claude API hatası: {e}\nSohbet sıfırlandı, tekrar deneyin.")
    finally:
        calisan_sohbetler.discard(chat_id)


async def onay_dugmesi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sorgu = update.callback_query
    if not yetkili_mi(update):
        await sorgu.answer("Yetkiniz yok.", show_alert=True)
        return
    _, onay_id, karar = sorgu.data.split(":")
    gelecek = bekleyen_onaylar.get(onay_id)
    if gelecek is None or gelecek.done():
        await sorgu.answer("Bu onay artık geçerli değil.")
        return
    gelecek.set_result(karar == "evet")
    await sorgu.answer()
    durum = "✅ Onaylandı, çalıştırılıyor..." if karar == "evet" else "❌ Reddedildi."
    await sorgu.edit_message_text(f"{sorgu.message.text}\n\n{durum}")


async def baslat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"Merhaba! Telegram ID'niz: {update.effective_user.id}\n\n"
        "Bana müşteri sorununu yazın, örneğin:\n"
        "\"Muhasebe PC'sinde yazıcı çalışmıyor\"\n\n"
        "Komutlar:\n/cihazlar – bağlı bilgisayarları listele\n/yeni – yeni sorun için sohbeti sıfırla"
    )


async def yeni(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not yetkili_mi(update):
        return
    sohbetler.pop(update.effective_chat.id, None)
    await update.message.reply_text("🆕 Sohbet sıfırlandı. Yeni sorunu yazabilirsiniz.")


async def cihazlar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not yetkili_mi(update):
        return
    try:
        liste = await meshcentral.cihazlari_listele()
    except Exception as e:
        await update.message.reply_text(f"MeshCentral'a bağlanılamadı: {e}")
        return
    if not liste:
        await update.message.reply_text("Kayıtlı cihaz yok.")
        return
    satirlar = [f"{'🟢' if c['cevrimici'] else '🔴'} {c['ad']} — {c['isletim_sistemi'] or '?'}" for c in liste]
    await mesaj_gonder(context, update.effective_chat.id, "\n".join(satirlar))


def main() -> None:
    eksik = [d for d in ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "MESHCENTRAL_URL",
                         "MESHCENTRAL_KULLANICI", "MESHCENTRAL_SIFRE", "MESHCTRL_YOLU")
             if not os.environ.get(d)]
    if eksik:
        raise SystemExit(f".env dosyasında eksik ayar(lar): {', '.join(eksik)}")
    if not IZINLI_KULLANICILAR:
        log.warning("IZINLI_KULLANICILAR boş! Bot kimseden komut kabul etmeyecek. "
                    "Telegram'da /start yazarak ID'nizi öğrenip .env'e ekleyin.")

    uygulama = (
        Application.builder()
        .token(os.environ["TELEGRAM_BOT_TOKEN"])
        .concurrent_updates(True)  # agent onay beklerken düğme tıklamaları işlenebilsin
        .build()
    )
    uygulama.add_handler(CommandHandler("start", baslat))
    uygulama.add_handler(CommandHandler("yeni", yeni))
    uygulama.add_handler(CommandHandler("cihazlar", cihazlar))
    uygulama.add_handler(CallbackQueryHandler(onay_dugmesi, pattern=r"^onay:"))
    uygulama.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mesaj_geldi))

    log.info("Destek agent'ı çalışıyor. Durdurmak için Ctrl+C.")
    uygulama.run_polling()


if __name__ == "__main__":
    main()
