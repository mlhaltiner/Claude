# Telegram BT Destek Agent'ı – Kurulum Rehberi (Windows)

Telegram'dan sorunu yazarsınız. Agent, MeshCentral üzerinden müşteri bilgisayarına bağlanır,
sorunu teşhis eder, **sizin onayınızla** düzeltir ve rapor verir.

```
Siz (Telegram) ──► bot.py (Claude) ──► MeshCentral sunucusu ──► Müşteri PC'deki ajan
```

İlk testte bu parçaların **hepsi sizin bilgisayarınızda** çalışacak. Kendi bilgisayarınız hem
"sunucu" hem de "müşteri" olacak.

Toplam süre: yaklaşık 30–45 dakika.

---

## Adım 0 – Gerekenler

| Gereken | Nereden | Ücret |
|---|---|---|
| Node.js (LTS sürümü) | https://nodejs.org | Ücretsiz |
| Python 3.10 veya üstü | https://www.python.org/downloads | Ücretsiz |
| Telegram hesabı | Telefonunuzdaki Telegram | Ücretsiz |
| Anthropic API anahtarı | https://console.anthropic.com | Kullandıkça öde |

> Python'u kurarken ilk ekrandaki **"Add python.exe to PATH"** kutusunu mutlaka işaretleyin.

---

## Adım 1 – MeshCentral'ı kurun

**PowerShell'i yönetici olarak açın** (Başlat → "PowerShell" yazın → sağ tık → *Yönetici olarak çalıştır*):

```powershell
mkdir C:\meshcentral
cd C:\meshcentral
npm install meshcentral
node node_modules\meshcentral
```

Ekranda `MeshCentral HTTPS server running on port 443` benzeri bir yazı görünecek.
**Bu pencereyi kapatmayın.**

1. Tarayıcıda **https://localhost** adresini açın. "Bağlantınız gizli değil" uyarısı normaldir:
   *Gelişmiş → Devam et* deyin.
2. **Create Account** ile ilk hesabı oluşturun. İlk oluşturulan hesap otomatik olarak yöneticidir.
   Kullanıcı adını ve şifreyi not edin, Adım 4'te lazım olacak.

> 443 portu doluysa (IIS, Skype vb.) MeshCentral hata verir. O zaman o programı kapatın.

## Adım 2 – Kendi bilgisayarınıza ajanı kurun ("müşteri" rolü)

1. MeshCentral panelinde **"Add Device Group"** (cihaz grubu ekle) deyin ve grubun adını
   **"Test"** yapın.
2. Grubun yanındaki **"Add Agent"** (ajan ekle) bağlantısına tıklayın, **Windows** seçin ve dosyayı indirin.
3. İndirilen dosyayı çalıştırın ve **Install** deyin.
4. Panelde bilgisayarınızın adı görünmeli. Çevrimiçi olduğunu gösteren ikon yanmalı.

> Gerçek müşterilerde de aynı şekilde: her müşteri için bir grup açıp ajanı oraya kurarsınız.

## Adım 3 – Telegram botunu oluşturun

1. Telegram'da **@BotFather**'ı açın ve `/newbot` yazın.
2. Bota bir ad verin, örneğin "Şirketim Destek". Ardından `_bot` ile biten bir kullanıcı adı verin,
   örneğin `sirketim_destek_bot`.
3. BotFather size şuna benzer bir **token** verecek: `123456789:AAH...`. Bunu not edin.

> Token, botunuzun şifresidir. Kimseyle paylaşmayın.

## Adım 4 – Agent'ı kurun

Bu depoyu bilgisayarınıza indirin. GitHub'da **Code → Download ZIP** deyip `C:\destek` klasörüne
açabilirsiniz. Sonra **yeni bir PowerShell** penceresinde:

```powershell
cd C:\destek\destek-agent
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
notepad .env
```

> `Activate.ps1` "çalıştırılamaz" hatası verirse önce şunu çalıştırın:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

Açılan Not Defteri'nde `.env` dosyasını doldurun:

| Ayar | Ne yazılacak |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys bölümünden aldığınız anahtar |
| `TELEGRAM_BOT_TOKEN` | Adım 3'te aldığınız token |
| `IZINLI_KULLANICILAR` | Şimdilik boş bırakın, Adım 5'te dolduracağız |
| `MESHCENTRAL_URL` | `wss://localhost:443` (aynı kalsın) |
| `MESHCENTRAL_KULLANICI` / `MESHCENTRAL_SIFRE` | Adım 1'de oluşturduğunuz hesap |
| `MESHCTRL_YOLU` | `C:\meshcentral\node_modules\meshcentral\meshctrl.js` |

## Adım 5 – Çalıştırın

```powershell
python bot.py
```

1. Telegram'da botunuzu bulun ve `/start` yazın. Bot size **Telegram ID**'nizi söyleyecek.
2. Bu ID'yi `.env` dosyasında `IZINLI_KULLANICILAR=` satırına yazın.
3. PowerShell'de **Ctrl+C** ile botu durdurun ve `python bot.py` ile yeniden başlatın.
4. Telegram'da `/cihazlar` yazın. Bilgisayarınız 🟢 ile görünmeli.

---

## Adım 6 – TEST: Agent sorunu çözebiliyor mu?

### Test 1: Yazıcı servisi durmuş (değişiklik + onay testi)

1. **Sorunu oluşturun.** Yönetici PowerShell'de şunu çalıştırın:
   ```powershell
   Stop-Service Spooler
   ```
   Artık bilgisayarınızda yazdırma servisi çalışmıyor.
2. Telegram'dan bota şunu yazın:
   > Bilgisayarımda yazıcıdan çıktı alamıyorum, yazıcılar görünmüyor.
3. **Beklenen davranış:**
   - 🔎 Bot `Get-Service Spooler` gibi okuma komutlarıyla durumu kontrol eder. Bunlar onaysız çalışır.
   - ⚠️ "Spooler servisi durmuş, başlatayım mı?" diye **✅ Onayla / ❌ Reddet** düğmeleriyle sorar.
   - ✅ Onayladığınızda servisi başlatır, tekrar kontrol eder ve rapor verir.
4. **Doğrulayın.** PowerShell'de `Get-Service Spooler` yazın. Sonuç **Running** olmalı.

### Test 2: Sadece bilgi alma

> Bilgisayarın C diskinde ne kadar boş yer var, en çok RAM kullanan 5 program hangisi?

Onay istemeden cevap vermeli.

### Test 3: Reddetme

Test 1'i tekrar yapın, ama bu sefer **❌ Reddet** deyin. Agent komutu çalıştırmamalı ve size
elle yapılacak adımları anlatmalı.

Her yeni sorundan önce `/yeni` yazarak sohbeti sıfırlayın.

---

## Güvenlik

- Bot yalnızca `IZINLI_KULLANICILAR` listesindeki Telegram hesaplarını dinler.
- Bilgi okuyan komutlar (`Get-...`, `ipconfig`, `ping` vb.) onaysız çalışır. **Değişiklik yapan
  her komut** sizin onayınızı bekler. Her komutu onaya bağlamak için `.env`'de
  `OKUMA_KOMUTLARI_ONAYSIZ=false` yapın.
- Yapılan her işlem `loglar\YYYY-AA-GG.jsonl` dosyasına kaydedilir. Müşteriye rapor verirken kullanabilirsiniz.
- `.env` dosyasını kimseyle paylaşmayın ve GitHub'a yüklemeyin (`.gitignore` bunu engeller).
- Gerçek müşteriye geçmeden önce müşteriden **yazılı uzaktan erişim izni** alın (KVKK).

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| `/cihazlar` → "MeshCentral'a bağlanılamadı" | MeshCentral penceresi açık mı? `.env`'deki kullanıcı adı, şifre ve `MESHCTRL_YOLU` doğru mu? |
| `'node' is not recognized` | Node.js kurulduktan sonra PowerShell'i kapatıp yeniden açın. |
| `'python' is not recognized` | Python'u "Add to PATH" kutusu işaretli olarak yeniden kurun. |
| Bot cevap vermiyor | `python bot.py` penceresindeki hata mesajına bakın. Telegram ID'niz `.env`'de var mı? |
| Cihaz 🔴 görünüyor | Ajan servisi çalışıyor mu? (Hizmetler → "Mesh Agent") |

## Sonraki adımlar (gerçek kullanım)

1. MeshCentral'ı küçük bir VPS'e taşıyın (aylık ~5–10 $), örneğin `destek.sirketiniz.com` adresine.
   Müşteri ajanları bu adrese bağlanır.
2. `bot.py`'yi aynı sunucuda sürekli çalışacak şekilde ayarlayın.
3. Her müşteri için MeshCentral'da ayrı bir grup açın.
