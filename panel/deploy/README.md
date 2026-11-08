# BYTE paneli: kurulum ve işletme rehberi

Panel, BYTE'ın ürettiği videoları görmeni, onaylamanı, takvime koymanı ve servislerin
sağlığını izlemeni sağlar. Adres: `https://byte.semihkopcal.com`

> Bu rehberdeki Cloudflare, GitHub ve Tailscale ekran adları zamanla değişebilir. Menü
> adı tutmazsa ilgili ürünün güncel dokümanına bak; mantık aynı kalır.

## 1. Nasıl çalışıyor

```
GitHub Actions "daily"  ──mp4 + kayıt──►  Cloudflare R2 (özel bucket)  ◄──okur/yazar──  PANEL (senin sunucun, Docker)
                                                                                           ▲
GitHub Actions "panel-publish" ◄──workflow_dispatch── PANEL                                │ cloudflared tüneli
        │                                                                                  │ (dışarı çıkan bağlantı)
        └──► YouTube / Instagram / TikTok                                     Cloudflare Access (e-posta girişi)
                                                                                           ▲
                                                                                         sen
```

- **Video üretimi GitHub Actions'ta kalır.** Bitince video R2'ye konur ve panelde "onay bekliyor" olarak belirir.
- **Panel yayın yapmaz, emir verir.** Onayladığında ve takvimdeki saat gelince GitHub'a "şu videoyu şu platforma yayınla" der. Platform token'ları (YouTube, Instagram, TikTok) **sunucuna hiç gelmez**, GitHub Secrets'ta kalır.
- **Sunucuda gelen kapı yok.** Hiçbir port dışarı açılmaz. Panele tek yol, sunucudan *dışarı* çıkan cloudflared tünelidir ve önünde Cloudflare Access (e-posta girişi) durur. Panel ayrıca her istekte Access'in imzalı kimlik belgesini kendisi doğrular; doğrulayamazsa kapıyı kapalı tutar.
- **Sunucu yönetimi (SSH)** yalnızca Tailscale ağından yapılır.

### Panelde ne var

| Sayfa | Ne yapar |
|---|---|
| Panel (ana sayfa) | Onay bekleyenler, yaklaşan yayınlar, **otomasyon** (onaysız yayın) anahtarı, **Duraklat** (acil durdurma) |
| Videolar | Tüm videolar, önizleme, onayla/reddet/onayı geri al, platform bazında durum |
| Takvim | Yaklaşan yayınlar: saati değiştir (Taşı), **Şimdi** yayınla, İptal, Yeniden dene |
| Ayarlar | Platformları aç/kapat, YouTube gizliliği, yayın saatleri (UTC), saklanacak video sayısı (varsayılan 100) |
| Servisler | "Her şey yolunda mı?" sayfası: R2, GitHub, son üretim ve yayın koşuları, senaryo kuyruğu, platform durumu |
| Kayıt | Kim ne zaman ne yaptı (denetim kaydı) |

**100 video kuralı:** R2'de en yeni 100 videonun dosyaları tutulur. Fazlası silinir, panelde satırı "arşiv" olarak kalır. YouTube/Instagram/TikTok'ta yayınlanmış videolara dokunulmaz. Onay bekleyen ya da takvimde olan video asla silinmez.

## 2. Başlamadan önce

- Docker ve Docker Compose v2 kurulu bir Linux sunucu.
- `semihkopcal.com` alan adının DNS'i **Cloudflare'de** olmalı (tünel adresi için).
- Cloudflare hesabında 2 adımlı doğrulama açık. Aynısı GitHub ve alan adı sağlayıcın için de.
- **Hiçbir anahtarı, token'ı ya da şifreyi sohbete yapıştırma.** Aşağıdaki komutlar bunları doğrudan sunucuda dosyaya yazar.

## 3. R2 (video deposu)

1. Cloudflare panelinde **R2 → Create bucket**: ad `byte-videos`. **Public erişimi AÇMA**, özel alan adı da bağlama. Panel videoyu izlemen için 5 dakikalık imzalı adres üretir.
2. **R2 → Manage API tokens → Create API token**, **iki ayrı token** oluştur (biri sızarsa ötekine dokunmadan iptal edersin):
   - `byte-ci`: izin *Object Read & Write*, kapsam **yalnız `byte-videos`**.
   - `byte-panel`: aynı izin, aynı kapsam.
3. Adres `https://<HESAP_KIMLIGI>.r2.cloudflarestorage.com` biçimindedir (R2 sayfasında "S3 API" altında yazar).
4. Ücretsiz kota ve fiyatlar değişebilir; 100 video yaklaşık 4 GB tutar. Güncel fiyata bak.

## 4. GitHub tarafı

**Secrets** (Settings → Secrets and variables → Actions → *Secrets*), `byte-ci` token'ından:

- `R2_ENDPOINT`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`

YouTube, Instagram ve TikTok secret'ların zaten orada; aynen kalıyor.

**Panelin GitHub anahtarı:** Settings → Developer settings → Personal access tokens → **Fine-grained tokens**:

- Repository access: **yalnız `SemihKopcal/byte-shorts`**
- Permissions: **Actions: Read and write**, **Contents: Read-only** (Metadata otomatik gelir)
- Bitiş tarihi koy (en fazla 1 yıl) ve takvimine hatırlatıcı ekle.
- Bu token'ı GitHub secret'ı olarak **ekleme**; yalnız sunucuya gider (aşağıda `secrets/github_token`).

**Önerilen sertleştirme:** Settings → Actions → General → *Fork pull request workflows* bölümünde dışarıdan gelen PR'larda onay iste.

**`PANEL_MODE` değişkeni** (Settings → Secrets and variables → Actions → *Variables*): panel çalıştığını doğruladıktan **sonra** `PANEL_MODE=on` yap. Açıkken `daily` videoyu üretir ama YouTube/Instagram/TikTok'a göndermez; R2'ye koyar. `AUTO_PRIVACY` bu modda yok sayılır (gizlilik panelde ayarlanır). Değişkeni silersen eski doğrudan yayına dönersin.

## 5. Cloudflare Access (giriş kapısı)

Önce Access'i kur, **sonra** tüneli yayına al; yoksa adres kısa süre korumasız kalır. (Panel yine de geçerli Access belgesi olmayan her isteği reddeder, ama kapıyı iki katman yapıyoruz.)

1. **Zero Trust → Access → Applications → Add an application → Self-hosted.**
2. Domain: `byte.semihkopcal.com`.
3. Policy: **Allow**, kural **Emails** = yalnız senin e-postan. Başka kural ekleme.
4. Oturum süresini kısa tut (örn. 24 saat).
5. Uygulama oluşunca **Application Audience (AUD) Tag** değerini kopyala → `.env` içinde `CF_ACCESS_AUD`.
6. Takım alan adın (`<takim>.cloudflareaccess.com`, Zero Trust ayarlarında yazar) → `.env` içinde `CF_ACCESS_TEAM_DOMAIN`.

## 6. Tünel

1. **Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared.** Ad: `byte-panel`.
2. Ekranda gösterilen kurulum komutundaki token'ı kopyala (sohbete yapıştırma).
3. **Public hostname** ekle: `byte.semihkopcal.com` → Service **HTTP** → `panel:8000`. DNS kaydı kendiliğinden oluşur.

## 7. Sunucu güvenliği (Tailscale)

Bu adımlar sunucu ayarı olduğu için **sen yaparsın**; Claude sunucuna erişemez.

1. Sunucuya Tailscale kur, `sudo tailscale up` ile tarayıcıdan giriş yap (anahtar yapıştırma yok).
2. Sunucu etiketi ver, erişimi yalnız kendi cihazlarına aç. Tailnet politika dosyası için örnek (sözdizimi için Tailscale dokümanına bak):

   ```json
   {
     "tagOwners": { "tag:server": ["autogroup:admin"] },
     "acls": [
       { "action": "accept", "src": ["autogroup:member"], "dst": ["tag:server:22"] }
     ]
   }
   ```

3. Güvenlik duvarı: gelen her şeyi reddet, yalnız Tailscale arayüzünden SSH'e izin ver.
   **Önce ikinci bir SSH oturumu açık tut**, sonra uygula; yoksa kendini dışarıda bırakabilirsin:

   ```bash
   sudo ufw default deny incoming
   sudo ufw default allow outgoing
   sudo ufw allow in on tailscale0 to any port 22 proto tcp
   sudo ufw enable
   ```

   Docker, yayınlanmış portlar için ufw'yi atlar. Bu kurulumda hiçbir port yayınlanmıyor; `docker-compose.yml` içine `ports:` ekleme.
4. Otomatik güvenlik güncellemeleri: `sudo apt install unattended-upgrades` ve `sudo dpkg-reconfigure -plow unattended-upgrades`.
5. SSH'te parola girişini kapat, yalnız anahtar kullan.

## 8. Panelin kurulumu

Her şey sunucuda `/srv/www/byte` altında durur:

```
/srv/www/byte/
├── app/        git deposu (kod). .env ve secrets/ app/panel/deploy/ içinde durur, git'e girmez
└── backups/    panel yedeklerinin kopyaları
```

Kod GitHub'dan gelir. Kurulumdan önce panelin kodunun `main`'e push edilmiş olması gerekir.

### Kolay yol: kurulum scripti

```bash
sudo mkdir -p /srv/www/byte && sudo chown "$USER": /srv/www/byte
git clone https://github.com/SemihKopcal/byte-shorts.git /srv/www/byte/app
bash /srv/www/byte/app/panel/deploy/server-setup.sh
```

Script önce sır olmayan ayarları sorar (R2 adresi, bucket, Access takım alan adı ve AUD etiketi, e-posta, cloudflared sürümü) ve `.env` dosyasını yazar. Sonra sırları ekranda görünmeden sorar ve doğrudan dosyaya yazar, `secrets/` izinlerini ayarlar, `docker compose config` ile doğrular ve onay verirsen paneli başlatır. Tekrar çalıştırmak güvenlidir: var olan `.env` ve secret dosyalarına dokunmaz, yalnız eksikleri sorar. Bir sırrı yenilemek için ilgili dosyayı sil ve scripti yeniden çalıştır.

### Elle kurmak istersen

```bash
cd /srv/www/byte/app/panel/deploy
cp .env.example .env
nano .env        # adresleri doldur. CLOUDFLARED_TAG: github.com/cloudflare/cloudflared/releases'tan güncel etiketi seç
```

Sırları **doğrudan dosyaya** yaz (komut geçmişinde ve sohbette iz kalmaz):

```bash
umask 077
read -rs -p "R2 access key id (byte-panel): " v; echo; printf '%s' "$v" > secrets/r2_access_key_id
read -rs -p "R2 secret access key (byte-panel): " v; echo; printf '%s' "$v" > secrets/r2_secret_access_key
read -rs -p "GitHub fine-grained token: " v; echo; printf '%s' "$v" > secrets/github_token
openssl rand -hex 32 | tr -d '\n' > secrets/csrf_secret
read -rs -p "Tünel token'ı: " v; echo; printf 'TUNNEL_TOKEN=%s\n' "$v" > secrets/tunnel.env
unset v

# panel konteyneri 10001 kullanıcısıyla okur: yalnız o ve root okuyabilsin.
# Sıra önemli: önce chmod (dosya hâlâ senin), sonra chown. Ters yaparsan chmod izin hatası verir.
chmod 400 secrets/r2_access_key_id secrets/r2_secret_access_key secrets/github_token secrets/csrf_secret
sudo chown 10001:10001 secrets/r2_access_key_id secrets/r2_secret_access_key secrets/github_token secrets/csrf_secret
chmod 700 secrets
chmod 600 secrets/tunnel.env
```

Başlat:

```bash
docker compose config -q          # hata vermezse ayarlar tam
docker compose up -d --build
docker compose ps                 # ikisi de "running"/"healthy" olmalı
docker compose logs -f panel
```

## 9. Doğrulama (hepsini yap)

```bash
# 1) Dışarıya açılan port yok:
docker compose port panel 8000      # hata verip boş dönmeli
ss -tlnp | grep -E ':8000' || echo "dinleyen yok (iyi)"

# 2) Adres Access girişine yönlendiriyor, panelin içini göstermiyor:
curl -sI https://byte.semihkopcal.com | head -5      # 302 ve cloudflareaccess.com görmelisin, 200 DEĞİL
```

3. Tarayıcıda adresi aç, kendi e-postanla gir: panel açılmalı.
4. Gizli pencerede **başka bir e-postayla** dene: Access reddetmeli.
5. Panelde **Servisler** sayfası: Veritabanı, R2, GitHub yeşil olmalı. Kırmızıysa sebebi yanında yazar.
6. GitHub'da `PANEL_MODE=on` yap, `daily`'yi elle çalıştır. Birkaç dakika içinde video panelde "onay bekliyor" olarak çıkmalı (panel 30 saniyede bir R2'ye bakar).
7. Videoyu önizle, onayla; Takvim'de yayın saatini gör. Hemen denemek için Takvim'deki **Şimdi** düğmesini kullan.

## 10. Günlük kullanım

- **Onay:** her video önce "bekliyor"dur (**Onayla**, **Reddet**, toplu için **Hepsini onayla**). Onaylayınca açık platformlar için takvimde bir saate (ayarlardaki saatlerden ilk boş olana) yerleşir.
- **Otomasyon anahtarı** (Panel sayfasında; "Kapalı: aç" / "AÇIK: kapat"): açıksa yeni videolar onaysız onaylanmış sayılır ve takvime girer. Kapatınca yine onayına düşer. Zaten onaylanmışlar etkilenmez.
- **Duraklat** (Panel sayfasında): tek tuşla hiçbir yeni yayın gönderilmez. Takvimdekiler bekler, silinmez.
- **Yayın saatleri** UTC'dir (Türkiye saati − 3). Varsayılan `01:15,07:15,13:15,19:15` = TR 04:15, 10:15, 16:15, 22:15.
- **Saatlik üst sınır:** saatte en fazla 12 yayın emri gönderilir (`PANEL_MAX_DISPATCH_PER_HOUR`).
- **Bir yayın "başarısız" olursa:** Takvim'de sebebi yazar. **Yeniden dene** elle yapılır; panel kendiliğinden tekrar denemez. Önce platformda video var mı diye bak. Zaten yayınlanmış bir videoyu iki kez yüklememek için yayın workflow'u R2'deki `ledger/` kaydına bakar.

## 11. Yedek, güncelleme, anahtar yenileme

**Yedek:** kayıtlar (videoların kendisi değil) SQLite'tadır. Günlük yedek için sunucunun crontab'ına:

```cron
0 3 * * * cd /srv/www/byte/app/panel/deploy && docker compose exec -T panel python -m bytepanel.backup
```

Son 14 yedek konteynerin `/data/backups` klasöründe (`panel-data` volume'u) tutulur. Haftada bir sunucudan çıkar: önce
`docker compose cp panel:/data/backups /srv/www/byte/backups/yedek-$(date +%F)` ile `/srv/www/byte/backups` altına al, sonra o klasörü sunucunun **dışına** (kendi bilgisayarına ya da başka bir depolamaya) taşı; aynı sunucudaki kopya sunucuyla birlikte kaybolur. Panel kaybolsa bile videolar R2'de, yayınlar platformlarda durur; kayıt kaybı yalnız onay geçmişini ve takvimi etkiler.

**Güncelleme:**

```bash
cd /srv/www/byte/app && git pull --ff-only && cd panel/deploy && docker compose up -d --build
```

Dependabot haftalık PR açar (hiçbiri kendiliğinden birleşmez); `audit` workflow'u her pazartesi bilinen güvenlik açıklarına bakar ve açık varsa kırmızı yanar.

**Bir anahtar sızdıysa ya da şüphelenirsen:**

| Anahtar | Ne yap |
|---|---|
| R2 token'ı | Cloudflare'de token'ı iptal et, yenisini üret, `secrets/` dosyasını (ya da GitHub secret'ını) güncelle, `docker compose up -d --force-recreate` |
| GitHub token'ı | GitHub'da iptal et, yenisini üret, `secrets/github_token`'ı değiştir, yeniden başlat |
| Tünel token'ı | Zero Trust'ta tüneli döndür (rotate), `secrets/tunnel.env`'i güncelle, yeniden başlat |
| CSRF sırrı | `openssl rand -hex 32 \| tr -d '\n' > secrets/csrf_secret`, yeniden başlat (açık formlar yenilenir) |
| Şüphe büyükse | Panelde **Duraklat**'a bas, sonra GitHub'da `PANEL_MODE` değişkenini sil |

## 12. Bilinen sınırlar (dürüst notlar)

- **"Tamamen güvenli" diye bir şey yok.** Burada risk katman katman düşürülüyor: açık port yok, giriş Cloudflare Access'te, panel belgeyi ayrıca doğruluyor, CSRF ve istek sınırı var, konteyner yetkisiz ve salt okunur, sırlar dosyada, platform token'ları sunucuda değil. Ama bu bir garanti değil. En zayıf halka genelde hesaplar: Cloudflare, GitHub, alan adı ve e-postan için 2 adımlı doğrulama şart.
- **Panel kapalıyken** üretim sürer, videolar R2'de bekler, **yayın yapılmaz** (otomasyon anahtarı da panel çalışırken işe yarar). Kayıp olmaz; panel dönünce hepsi görünür.
- **Instagram:** Reels için video adresini Instagram'ın indirebilmesi gerekir; bunun için R2'den 1 saatlik imzalı adres verilir. Bu yol gerçek hesapla henüz denenmedi; ilk denemede başarısız olursa sebebi Takvim'de yazar.
- **TikTok:** API yalnız taslak bırakır; TikTok uygulamasında "Paylaş"a basmak sana kalır.
- **Panel modunda `content/published.json` güncellenmez.** Yayın kaydının tek kaynağı panel (ve R2'deki `ledger/`). Senaryo kuyruğu `built.json` ile işlemeye devam eder.
- **Bir yayın workflow'u hiç başlayamazsa** (örn. GitHub kesintisi) panel 45 dakika sonra onu "başarısız" sayar ve sana gösterir; sessizce kaybolmaz.
- Panel tarafı gerçek Cloudflare, R2 ve GitHub hesaplarıyla bu geliştirme ortamında denenemedi. Testler sahte hizmetlerle çalışır; ilk kurulumda yukarıdaki doğrulama adımları gerçek denemedir.
