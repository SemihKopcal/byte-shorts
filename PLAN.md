# BYTE — yol haritası

Bu dosya "ne yapılacak"ı tutuyor. Her madde bittiğinde işaretlenecek.
Kararların **sebebi** de burada; altı ay sonra "neden böyle yapmıştık" diye
sorduğumuzda cevap kodun içinde değil burada olsun.

---

## Durum (6 Kasım 2026)

**Çalışıyor:** Piper sesi, 9 sahneli katalog, 8 tema, kapalı döngü
(Gemini yazar → editör yargılar → kod aritmetiği hesaplar → render → QC →
YouTube → defter → release). Günde 2 video (ilk 30 gün, A/B testi; sonra 4'e çıkılabilir), `AUTO_PRIVACY` değişkeniyle tek
düğmeli yayın kontrolü.

**Konu çeşitliliği (6 Kasım, kullanıcı isteği: "sadece bilgi değil ilgi çekici
konular da"):** dört biçim: `measured` (rakamlar), `story` (belgelenmiş olay,
zaman sırasıyla), `explain` (bir davranışın tek şaşırtıcı nedeni), `trend`
(gündem, birincil kaynakla karşılaştırma). Yapımcı 5 aday verir, merak çift
ağırlıklı, son üç videoda kullanılmayan biçim +2. Hikayede olay iddiaları
aramayla doğrulanır; **arama kapalıysa hiçbir şey doğrulanmış sayılmaz**
(fail-closed). Yedek havuz 20 konu: 12 ölçüm, 5 hikaye, 3 açıklama. İlk
haftada YouTube Analytics'te biçim başına izlenme/tutma karşılaştırılacak;
tutmayan biçimin ağırlığı `rank` içindeki bonustan ayarlanır.

**Yazılmış senaryolar (6 Kasım, kullanıcı kararı: "Gemini'yi boşverelim"):**
Konuları ve senaryoları Claude yazıyor ve doğruluyor; `content/plan.md` 100
videoluk yol haritası (45 hikaye, 30 ölçüm, 25 açıklama, hiçbir ardışık iki
video aynı biçimde değil). Kapı `editorial/authored.py`: ekran sayıları
hesapla ya da okunmuş bir sayfayla eşleşmek, kaynaklar https, her olay iddiası
`note` ile. Kod sayfayı okuyamaz; doğrulama yazarın okuduğu sayfadadır ve dosyada
isimle görünür. Sebep: ücretsiz anahtarda arama yok, aramasız Gemini hiçbir dış
olguyu doğrulayamıyor, ücretli arama için fatura bağlamak kullanıcı kararı değil.
İlk parti `p001`–`p010` yazıldı.

**Daily'den Gemini söküldü (8 Kasım, kullanıcı kararı: "hiç denemesin"):** 6–8
Kasım'daki 4 zamanlı koşu aynı adımda düştü ("konu üret", Gemini); senaryolar
repoya ulaşmadığı için sıra boştu ve Gemini'nin her adayı kapıda reddedildi
(`content/rejected`). Şimdi `daily.yml` ilk iş sırayı seçiyor; boşsa kurulum
yapmadan ~15 sn'de kırmızı duruyor, ≤4 senaryo kalınca uyarı yazıyor. Kuyruk
boşalınca yapılacak tek şey yeni parti yazmak. `editorial/` kodu repoda duruyor
ama daily'ye bağlı değil (`tests/test_daily.py` bunu denetliyor, `ci/` ile
`.github/workflows/` ayrışmasını da).

**Gemini anahtarı (6 Kasım, gemini-check #1):** ücretsiz katmanda Google
Search grounding yok (resmi fiyat sayfası). Sonuç: `story`/`trend` biçimleri
bu anahtarla çalışamaz; kod aramayı kendisi bırakıp yalnız `measured` ve
`explain` yazar. Çalışan modeller: 3.6-flash, 3.5-flash, 3.5-flash-lite,
3.1-flash-lite, 3-flash-preview; 3.8/3.7 aşırı yüklü (503); 2.5 ve 2.0 yeni
hesaplarda 404. Hikaye/gündem için seçenekler: (a) AI Studio'da faturalandırma
(ayda 5.000 arama bedava, sonrası 1.000'de 14 USD), (b) arama yerine kodun
çektiği birincil kaynak metniyle doğrulama (Wikipedia/HN/GitHub) yazmak.
Karar bekliyor.

**Panel (8 Kasım): yayında.** `byte.semihkopcal.com`, Access + tünel, sunucuda
çalışıyor; `PANEL_MODE` henüz kapalı (video hâlâ doğrudan yayınlanıyor).
Sıradaki panel işleri 6. bölümde: önce canlıya alma (6.0), sonra tasarım
yenileme (6.1), sonra panelden hesap bağlama (6.2).

**Sırada (öncelik sırasıyla):**

1. BYTE anlatıcı (aşağıda madde 1): `draw_byte_pointing` yazıldı, sahnelere
   bağlanmadı.
2. Animasyonlu arka plan (madde 2): mesh/ızgara/halka animasyonları için bir
   taslak yazıldı ama henüz repoda değil; önce BYTE anlatıcı bitecek.
3. Instagram + TikTok: **kod yazıldı ve test edildi** (6 Kasım): Instagram
   Reels tam otomatik, TikTok gelen kutusu taslağı (açıklamayı kullanıcı
   uygulamada yapıştırır). Hesap kurulumu, token'lar ve `GH_PAT` kullanıcıda
   (README "Instagram ve TikTok"). Gerçek bir yüklemeyle henüz denenmedi.
4. Editör geri bildirim döngüsü: YouTube Analytics (`yt-analytics.readonly`)
   verisini yapımcıya vermek; hangi konu/kanca tuttu.

**Karar kaydı — neden her şey otomatik public:** kullanıcı kararı. Risk:
YouTube Temmuz 2026 "sahte/şablon içerik" maddesi; savunma hattı üç katman:
çeşitlilik (tema, sahne, konu), editör kapısı (puan ≥ 7, kod aritmetiği,
arama doğrulaması), ve `AUTO_PRIVACY=off` kill-switch'i. İlk 10 videoda
YouTube Studio'da "Content" sekmesinden uyarı/kısıtlama bildirimlerine
bakılacak; biri gelirse önce `private`'a çekilip sebep okunacak.

---

## Kitle kararı: 10–30 yaş

Bu, sanılandan çok daha fazla şeyi değiştiriyor. Mevcut tasarım 30+ bir
okuyucuya göre: sakin, tablo ağırlıklı, sessiz. 10–30 için gereken:

| şu an | olması gereken |
|---|---|
| ilk 3 saniyede sakin bir başlık | ilk **1** saniyede çelişki |
| tablo okutuyoruz | tablo **anlatıyor**, BYTE gösteriyor |
| sahne başına ~3.5 sn | ~2.2 sn, ritim daha sık |
| tek koyu palet | video başına değişen tema |
| BYTE köşede küçük bir imza | BYTE **anlatıcı**, ekranda |

Dikkat: hızlanmak ≠ bağırmak. Abartılı başlık ve şok efekti
YouTube'un Temmuz 2026 "duygusal manipülasyon" maddesine giriyor. Hız
**kurgudan** gelecek, ses tonundan değil.

---

## 1. BYTE anlatıcı olsun  ·  ⬜

**Sorun:** BYTE şu an videoda 1–2 kez görünüyor, o da sahneler arası boşlukta.
Karakter yaratmanın amacı tanınırlık; görünmeyen karakter tanınmıyor.

**Yapılacak**

- [ ] `pointer` pozu: BYTE elinde bir çubuk tutuyor, çubuk ekrandaki veriyi
      gösteriyor. Çubuğun ucu hedefe göre açılanıyor (`angle_to(x, y)`).
- [ ] `presenter` yerleşimi: BYTE sol altta sabit, veri sağda. Tablo, çubuk
      ve zaman çizelgesi sahneleri bu yerleşimde de çalışacak — yani BYTE
      sahneyi **bölmüyor**, sahnenin içinde duruyor.
- [ ] Tepki: veri belirdiğinde imleç rengi değişsin (pahalıya amber, ucuza
      nane). Tek kare bile olsa izleyici bunu yakalıyor.
- [ ] Kural: her videoda BYTE süresinin **en az %40'ında** ekranda.

**Neden çubuk:** yüz yok, el kol hareketi sınırlı. Çubuk, yüz çizmeden
"şuraya bak" diyebilmenin tek yolu — ve yüz çizmemek bilinçli bir karar
(her karede tutarlılık + "uzman gibi konuşan yapay kişilik" maddesinden
uzak durmak).

---

## 2. Arka plan ve renk  ·  ⬜

**Sorun doğru:** tek koyu mor-siyah her videoda aynı. 30 video sonra
"hep aynı video" hissi veriyor, ki bu hem izleyici hem politika tarafında
kötü.

**Yapılmayacak:** stok fotoğraf, stok video, AI görseli. Üçü de
(a) "AI slop" görüntüsüne geri döndürür, (b) telif riski taşır,
(c) karakter tutarlılığını bozar.

**Yapılacak — tema sistemi**

- [ ] `worker/themes.py`: 6–8 tema. Her tema = arka plan rengi + ikincil
      renk + vurgu rengi + doku.
      ```
      midnight   koyu mor      (şimdiki)      nane vurgu
      ember      koyu bordo                   amber vurgu
      deep       koyu lacivert                camgöbeği vurgu
      moss       koyu yeşil-gri               limon vurgu
      slate      nötr koyu gri                mercan vurgu
      plum       koyu erik                    pembe vurgu
      ```
- [ ] Doku çeşitliliği: düz degrade / ince ızgara / nokta matrisi /
      tarama çizgisi / kontur haritası. Hepsi kodla, hepsi hafif.
- [ ] Tema **konuya göre** seçilsin: fiyat konusu → ember, hız → deep,
      karşılaştırma → slate. Rastgele değil, anlamlı.
- [ ] Kural: son 3 videonun teması tekrarlanmasın.

**Koyu kalmalı mı:** evet. Shorts çoğunlukla telefonda, çoğu gece
izleniyor; açık arka plan hem göz yoruyor hem metin kontrastını
düşürüyor. Çeşitlilik **renkten** gelecek, parlaklıktan değil.

> **Güncelleme (11 Kasım 2026):** karton/çizgi film stili eklendi (`worker/cartoon.py`, `brand.json` >
> `cartoon`). Açık **kâğıt** yüzü yukarıdaki "koyu kalmalı" kararını bilerek deler: referans kanalların
> görünümü bu ve temmuz 2026 politikası kalıp üretimi hedefliyor. Göz yorgunluğu riskini azaltan şeyler:
> kâğıt hep lacivertle **dönüşümlü** (sahne sahne), `share` ile videoların bir kısmı koyu kalabilir, metin
> kontrastı test ediliyor (`tests/test_cartoon.py`). İzleme süresi/ayrılma ölçümleri kötüleşirse ilk ayar:
> `share` düşür ya da `alternate` ile lacivert payını artır.

---

## 3. Güncel konu motoru  ·  ⬜

**Sorun:** Gemini konuyu eğitim verisinden buluyor — yani eski.

**Yapılacak**

- [ ] `tools/trends.py` — ücretsiz, anahtar istemeyen iki kaynak:
      - **Hacker News** (Algolia API): son 48 saat, AI/model/fiyat filtresi
      - **GitHub Search API**: son 7 günde hızlı yıldız toplayan AI repoları
- [ ] 30–40 aday başlık + link → Gemini'ye verilir
- [ ] Gemini birini seçer ve **ölçülebilir bir açı** bulur
- [ ] Seçtiği haberin linki kaynak listesine zorunlu olarak girer

**Açı kuralı** — kanalın tek ayırt edici özelliği bu:

> ❌ "Yeni model çıktı, inanılmaz"
> ✅ "Dün çıktı. Saniyesi ne tutuyor, ölçtüm."

Herkes duyuruyu anlatıyor; kimse faturayı hesaplamıyor. Güncellik
trafiği getirir, ölçüm bizi ayırır. İkisi olmadan biri işe yaramıyor.

Sonraki tur (şimdi değil): Reddit (r/LocalLLaMA), sağlayıcı fiyat
sayfalarının değişim takibi.

---

## 4. Ritim  ·  ⬜

- [ ] Sahne başına hedef 2.0–2.5 sn (şu an ~3.5)
- [ ] İlk beat en fazla 9 kelime
- [ ] Beat sayısı 14–18
- [ ] Her 4 beat'te bir sahne tipi **zorunlu** değişsin
- [ ] Kapanış 2 beat'i geçmesin

---

## 5. Yayın ve ölçüm  ·  ⬜

- [ ] İlk private yükleme (secrets testi)
- [ ] İlk public yayın
- [ ] 10 video sonrası: hangi sahne tipi, hangi tema, hangi konu daha iyi
      tuttu — izlenme ve ortalama izlenme süresine bakılacak
- [ ] O veri `brand.json`'a geri beslenecek (iyi tutan sahne tipleri daha
      sık seçilsin)

---

## 6. Panel  ·  🟨 v1 yayında (8 Kasım 2026)

Panel `byte.semihkopcal.com` adresinde: Cloudflare Tunnel + Access (yalnız
sahibinin e-postası), sunucuda `/srv/www/byte`, kurulum ve doğrulama
`panel/deploy/README.md`. Video üretimi GitHub Actions'ta kalıyor; panel
onay, takvim, duraklatma ve sağlık kontrolü yapıyor.

**Sıra (kullanıcı kararı, 8 Kasım): önce canlıya alma, sonra tasarım, sonra
hesap bağlama.**

### 6.0 Canlıya alma (açık işler)

- [x] Sunucuya kuruldu, Access girişi çalışıyor, güvenlik doğrulaması geçti
      (port yok, uid 10001, salt okunur, cap_drop ALL, bellek limiti)
- [x] Hata: `Referrer-Policy: no-referrer` tarayıcıya form gönderirken
      `Origin: null` yollattı, CSRF kontrolü her POST'u 403 yaptı. Düzeltme:
      `same-origin` (commit `cae337d`). **Ders:** testler tarayıcıyı birebir
      taklit etmiyordu → 6.1'de gerçek tarayıcı testi var
- [ ] Sunucuda güncelle (`git pull --ff-only` + `docker compose up -d --build`),
      Ayarlar'da bir düğmeyle "Ayar kaydedildi" mesajını gör
- [ ] `PANEL_MODE=on` (GitHub **Variables**) + elle bir `daily` koşusu →
      panelde onay bekleyen → onayla → `panel-publish` → YouTube. "Servisler"
      sayfasındaki "Yayın (panel-publish)" satırı yeşile dönmeli
- [ ] Günlük yedek cron'u (`README` bölüm 11) + haftalık sunucu dışı kopya
- [ ] Yeni senaryo partisi `p038`+: kuyrukta ~33 senaryo var, günde 2 videoyla
      ~16 günlük. Panelde "kuyruk kaç gün yeter" uyarısı 6.1'de
- [x] CI/CD sağlamlaştırma (9 Kasım): `check` artık panel imajını derleyip kısıtlı
      konteynerde açıyor, secret taraması (`tools/secret_scan.py`, haftalık geçmiş
      taraması `audit`'te), `render-smoke` (Dependabot güncellemeleri için gerçek render
      kapısı), `panel/deploy/update.sh` (yedekli, sağlık kontrollü, geri alan), workflow
      güvenlik testleri. Akış: README "Canlıya alma akışı".
- [ ] `daily`'yi ikiye böl: sırsız + yazmasız **render** job'u (üçüncü taraf ffmpeg burada
      çalışır) ve `contents: write` + sırları taşıyan **yayın/defter** job'u; ikisi artifact
      ile konuşur. Neden: `ffmpeg` ikilisi pinli değil (README "Bilinen artık risk"). GitHub'da
      denenmeden yapılmamalı: önce bir dalda `workflow_dispatch` ile.

### 6.1 Tasarım yenileme (detaylı)  ·  ⬜

**Amaç:** panel telefondan, tek elle, 10 saniyede "izle → onayla" yapılacak
kadar hızlı ve ilk bakışta "sistem sağlıklı mı" sorusuna cevap verecek kadar
net olsun. Şu an işlevsel ama düz: menü metin, kartlar sade, her şey aynı
ağırlıkta.

**Kısıtlar (güvenlikten, değişmez):** CSP `script-src 'self'; style-src 'self'`
→ satır içi script/stil yok, CSS/JS `static/` dosyası; harici font/CDN yok
(sistem fontu ya da barındırılan Inter); `img-src 'self' data:`; video yalnız
R2 sunucusundan. Tasarım bunların içinde kalacak.

- [ ] **Mobil öncelikli yerleşim:** alt gezinme çubuğu (Panel · Videolar ·
      Takvim · Servisler · Ayarlar), büyük dokunma hedefleri (≥ 44 px),
      iPhone güvenli alan boşlukları, tek sütun
- [ ] **Ana sayfa = durum özeti:** üstte tek satır "her şey yolunda / dikkat",
      altında bugün: onay bekleyen, bugünkü planlı yayınlar, son sonuçlar,
      **kuyruk kaç gün yeter** (≤ 4 senaryo kalınca sarı)
- [ ] **Onay ekranı:** 9:16 oynatıcı (poster kare ile), başlık/açıklama/etiket
      yan yana düzenlenebilir, üç net eylem: **Onayla ve planla · Hemen yayınla ·
      Reddet**; sonraki bekleyene geçiş; klavye kısayolları (A / R / →);
      toplu onay
- [x] **Takvim:** ay ızgarası + gün sayfası (Türkiye saati), tıkla → video/saat seç,
      sürükle-bırak, otomatik doldur, haftalık şablon, üretim tahmini, A/B kolları,
      kuyruk kaç güne yeter
- [ ] **Takvim (kalan):** hafta görünümü; duraklatılmış ve geciken yayınlar ayrı renkte;
      dokunmatikte sürükleme (şimdilik gün sayfasındaki "Taşı")
- [ ] **Servisler:** her satırda durum rengi + kısa neden + "ne yapmalı"
      (örn. "GitHub token süresi doluyor → yenile"); token bitiş tarihleri
- [ ] **Açık/koyu tema** (`prefers-color-scheme`), tek tutarlı renk sistemi,
      durum renkleri yalnız renge güvenmez (simge + metin)
- [ ] **Boş / hata / bekleme durumları:** anlaşılır Türkçe metin, flash
      mesajları toast olarak (ekrandan kendiliğinden kaybolur)
- [ ] **Ölçüm sayfası:** yayınlananların izlenme/tutma verisi (bölüm 5 ile
      ortak, `yt-analytics.readonly`)
- [x] **Begen / takip CTA'si:** kapanis karti + sesli cumle + kose etiketi + aciklama satiri
      + sabitlenecek yorum metni; deney kollarina da ayni (README "Begen / takip CTA'si")
- [x] **Video stili:** kamera hareketi (5), gecis efekti (5), doku, anlatim temposu; senaryo
      kimliginden deterministik (README "Video stili")
- [ ] **Cesitlilik (kalan):** yeni sahne turleri (acilis/kapanis varyantlari), ses efektleri
      (gecis "whoosh", chip tiki), ikinci ses; yeni senaryo partisinde bicim/acilis kotalari
- [ ] **CTA (kalan):** panelde sabitlenecek yorumu video sayfasinda goster + kopyala;
      CTA'li / CTA'siz videolari olcum sayfasinda ayri izle
- [ ] **Erişilebilirlik:** kontrast WCAG AA, görünür odak halkası, klavye ile
      tam kullanım
- [ ] **Gerçek tarayıcı testi** (Playwright): giriş sonrası gerçek form POST'u,
      mobil genişlik, CSP ihlali olmadığını konsoldan denetleme. Sebep:
      `Origin: null` hatası birim testlerde görünmedi

### 6.2 Panelden hesap bağlama  ·  ⬜

**Amaç:** yeni hesap/kanal eklemek (YouTube, Instagram, TikTok; ileride ikinci
kanal) terminal ve GitHub secret'ı ile uğraşmadan panelden "Bağla" ile
yapılsın.

- [ ] **Hesaplar sayfası:** platform, hesap adı, durum, token bitiş tarihi,
      Bağla / Yenile / Kes; bağlama ve kesme eylemleri denetim kaydına yazılır
- [ ] **OAuth akışı:** panelde Bağla → platformun izin ekranı → geri dönüş
      `https://byte.semihkopcal.com/oauth/<platform>/callback` (her platformda
      yönlendirme adresi olarak kayıtlı olmalı; adres Access arkasında) →
      panel kodu token'a çevirir. `state` ve PKCE zorunlu
- [ ] **Çoklu hesap:** yayın isteği hangi hesaba gideceğini taşır (`account`
      alanı); `panel-publish.yml` buna göre token seçer
- [ ] **Token uyarıları:** süre dolmadan Servisler'de sarı, dolunca kırmızı;
      Instagram uzun ömürlü token ~60 gün yenilenir, TikTok erişim token'ı
      kısa ömürlü (yenileme token'ı ile), Google OAuth uygulaması "Testing"
      modundaysa yenileme token'ı 7 günde ölür → yayında olduğunu doğrula
- [ ] **Geçiş:** bugün YouTube anahtarları GitHub secret'ında (`YT_*`),
      Instagram/TikTok `tokens.yml` + `GH_PAT`'te. Panelden bağlama bunların
      yerini alacaksa mevcut CI akışı bozulmadan geçilecek, eski yol silinmeden
      önce yenisi bir gerçek yüklemeyle denenecek

**Karar bekliyor (kod yazmadan önce konuşulacak): token nerede durur?**

- **A — Panelde şifreli, yayın anında CI'ya kısa ömürlü verilir.** Panel
  ele geçirilirse yalnız bağlı hesaplar risk altında; CI'nın diğer sırlarına
  dokunulmaz. Dispatch girdileri Actions günlüğünde görünür → token girdi
  olarak geçmez, maskeleme/geçici R2 paketi gerekir (iş biraz karmaşıklaşır).
- **B — Panel GitHub secret'ını API ile yazar.** Basit; ama panelin GitHub
  token'ına `Secrets: write` yetkisi gerekir → panel ele geçirilirse CI'daki
  **bütün** sırlar tehlikeye girer. Mevcut tasarımın "panel en az yetkiyle
  çalışır" ilkesine ters.
- **Öneri:** A. Platform kısıtları (TikTok denetim başvurusu, Instagram
  Professional hesap ve Meta uygulaması) 7. bölümdeki işlerle birlikte
  değerlendirilecek.

---

## 7. Diğer platformlar  ·  ⬜

- [x] Kod: `publish/instagram.py`, `publish/tiktok.py`, `tools/host_video.sh`,
      `tools/tiktok_login.py`, `tokens.yml`, `media-init.yml`, defter
      `content/social.json`, 28 test
- [x] Handle: YouTube `@byte-knowledge`; Instagram/TikTok `@byte_knows`
      (hesaplar açıldı, 8 Kasım; YouTube şimdilik `@byte-knowledge` kalıyor)
- [ ] Instagram: Professional hesap, Meta uygulaması, token, `media-init`, Pages
- [ ] TikTok: geliştirici uygulaması, `tiktok_login.py`, secret'lar
- [ ] İlk gerçek yükleme ikisinde de (mod `public` iken)
- [ ] TikTok Content Posting API **denetim başvurusu** (dolunca doğrudan
      yayın + açıklama API'den gider; o zamana kadar taslak)
- [ ] Facebook Reels: aynı Meta uygulamasıyla eklenebilir

---

## Değişmeyecek kurallar

Bunlar tartışmaya açık değil, çünkü ihlal edildiğinde kanal ölüyor:

1. **Her görsel kodla çizilir.** Stok yok, AI görseli yok.
2. **Ekrandaki her sayı kaynaklıdır.** Emin olunmayan sayı videoya girmez;
   konu değiştirilir.
3. **BYTE makinedir.** Uzman taklidi yapmaz, tavsiye vermez.
   Sağlık/finans/hukuk/siyaset konusu açılmaz.
4. **Hiçbir video onaysız yayınlanmaz.** `daily` üretir, `publish` elle
   çalışır.
5. **Kesmeler seslendirmeye oturur**, sabit sayaca değil. Sabit sayaç =
   slideshow = elenen kategori.
