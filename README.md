# byte-shorts

BYTE kanalinin uretim hatti. Gunde 2 video, hepsi kodla ciziliyor, konular
`content/scripts` kuyrugundaki yazilmis senaryolardan geliyor (Gemini yok),
YouTube'a kendiliginden yukleniyor; Instagram Reels'e kendiliginden, TikTok'a
taslak olarak gidiyor.

> `editorial/` (Gemini) asagidaki semada duruyor ama **daily'ye bagli degil**
> (8 Kasim karari). Kod repoda, ileride faturali anahtarla geri baglanabilir;
> su an daily yalniz `content/scripts` kuyrugunu isliyor.

```
        ┌───────────────────────────── editorial/ (Gemini) ─────────────────────────────┐
canli   │ yapimci → yazar → editor ⇄ yazar (en fazla 2 tur) → sanat yon. → metin yazari │
sinyal ─┤   5 konu    senaryo   yargi + sayi/olay        revize    tema     baslik +    │
        │   4 bicim   JSON      iddialari; KOD hesaplar            secer    3 platform   │
        │   kod eler  arama destekli dogrulayici: formulsuz rakam ve olaylari kontrol eder│
        └──────────────────────────────────┬────────────────────────────────────────────┘
                                           ▼ content/scripts/<id>.json
        worker/  synth (Piper) → sahneler → Pillow → ffmpeg → qc
                                           ▼ out/<id>/<id>.mp4 + manifest.json + captions.md
        publish/youtube.py  AUTO_PRIVACY ile yukle     tools/release.sh  Release'e koy
        publish/instagram.py  Reels (video GitHub Pages'ten)   publish/tiktok.py  gelen kutusu taslagi
```

## Gunluk akis (`daily.yml`, 04:15 ve 13:15 UTC)

1. `content/scripts/` icindeki siradaki islenmemis senaryo alinir (asagida
   "Yazilmis senaryolar"). Bu, kosunun **ilk isi**: ffmpeg/font/pip/ses modeli
   kurulumundan once. Gemini yok, API anahtari gerekmez.
2. Kuyruk bossa kosu ~15 saniyede **kirmizi** durur ("Kuyruk bos"), hicbir sey
   kurulmaz, dakika yanmaz; yeni parti yazilana kadar her kosu boyle biter.
   Kuyrukta 4 ya da daha az senaryo kalinca uyari yazar (kirmizi degil).
3. Video cizilir, `worker/qc.py` kontrol eder (sure, en-boy, ses, tekrar,
   kaynak, yayin metni).
4. `AUTO_PRIVACY` ne diyorsa o gizlilikle YouTube'a yuklenir.
5. `content/built.json` ve `published.json` repoya geri yazilir.
6. Video + Instagram/TikTok metinleri bir GitHub Release'e konur
   (telefondan indirilebilir).
7. Yayin modu `public` ve ilgili secret'lar varsa: video `media` dalina
   konur (GitHub Pages), Instagram Reels olarak yayinlanir, TikTok'a
   gelen kutusu taslagi olarak yuklenir. Bu iki adim **uyari olarak** kirmizi
   biter: patlarlarsa YouTube yuklemesini ve kosuyu bozmazlar.

## Yazilmis senaryolar (Gemini'siz, 100 gunluk kuyruk)

Konulari Claude secip yaziyor ve dogruluyor; plan `content/plan.md`. Senaryolar
`content/scripts/pNNN-<ad>.json`, dosya adi sirasiyla alinir (`pick_script.py`
siralayip islenmemis ilkini secer). Dosyada `"authored": {"by", "date"}` varsa
`editorial/authored.py` kapisindan gecmek zorunda:

- alanlar: `id` (dosya adiyla ayni), `series` "G", `lang`, `format`
  (measured | story | explain), `title` (<= 60), `summary`, `tags`, `sources`
  (2-6 tane, https), `beats` (10-18), `claims`, `facts`, `copy_parts`, `authored`
- `rules.validate_script`: sure <= 52 sn, 4+ sahne, hook/why/data/turn/resolve
  sirasi, hook <= 12 kelime, `say` icinde rakam yok
- `claims`: ekrandaki her anlamli sayi (10'dan buyuk, yil degil) ya `expr`+`value`
  ile hesaplanir (kod hesaplar) ya da `source` + `note` ile bir sayfaya baglanir
- `facts`: hikayede en az 2 olay iddiasi, her biri kaynak numarasi ve `note` ile
- her kaynak en az bir iddiada kullanilmali; `copy_parts` yayin metnini kurar

Kod bir sayfanin ne dedigini okuyamaz. Bu yuzden her kaynakli iddianin `note`
alani sayfanin ne dedigini yazar ve senaryo o not olmadan kapidan gecmez; yani
dogrulama kodda degil, yazarin okudugu sayfada. Kontrol:

```bash
python -m editorial.authored          # hepsi, sorun varsa cikis kodu 1
python -m editorial.authored p003-air-canada-chatbot
```

Kuyruk 100 senaryoda biter: gunde 1 videoyla 100 gun, gunde 2 videoyla 50 gun.
Bitince daily "Kuyruk bos" diye kirmizi durur (Gemini'ye dusmez); yeni parti
zamaninda yazilmali. Kuyruk sirasi dosya adi sirasidir, bu yuzden `pNNN-`
numarasi plandaki siradir.

## Konu bicimleri: bilgi + ilgi

Kanal sadece olcum yapmiyor; dort bicim donuyor (`editorial/roles.py`):

| bicim | ne anlatir | dogrulama |
|---|---|---|
| `measured` | rakamlar hikaye: fiyat, bayt, token aritmetigi | editor formul yazar, **kod hesaplar** |
| `story` | belgelenmis bir olay, zaman sirasiyla (kapatilan bot, mahkemeye giden chatbot, icinde insan olan makine) | olay/tarih iddialari **aramayla** dogrulanir, en az 2 iddia sart |
| `explain` | bir yapay zeka davranisinin tek sasirtici nedeni, tek ornekle | gosterilen sayi turetilebilir olmali |
| `trend` | bu hafta konusulan sey, birincil kaynakla karsilastirilmis | iddia basina arama dogrulamasi |

Yapimci 5 aday uretir (en az 3 farkli bicim). Kod eler: dogrulanabilirlik,
**merak** ve guvenlik puani 7'nin altindaysa gider. Siralamada merak iki kat
sayilir; son uc videoda kullanilmayan bicim +2, kullanilan her tekrar -2 alir,
yani kanal ayni bicimi ust uste uretmez ama zayif bir hikaye guclu bir olcumun
onune de gecmez. Yedek havuz (`content/backlog.json`) ayni mantikla doner.

**Arama kapaliysa hicbir sey dogrulanmis sayilmaz.** Model aramasiz "dogruladim"
derse hafizasindan konusuyordur; bu kanit degil. O durumda yalniz formulle
kanitlanan icerik yayina girer, hikaye/gundem konulari elenir ve log nedenini
soyler. Bilincli gevsetmek istersen `ALLOW_UNVERIFIED` degiskeni (0-5,
varsayilan 1): dogrulanamayan en fazla kac iddia kabul.

**Ucretsiz anahtarla:** arama (grounding) yok. Kod bunu kosunun basinda bir
kez yoklar; yapimci ve yazar prompt'ta "arama kapali, yalniz aritmetik"
notunu gorur, `story`/`trend` adaylari elenir, aday azsa yedek havuzdan
tamamlanir, 5'ten fazla dogrulanamayan iddiaya dayanan konu revizyon turu
harcamadan birakilir. Ama durust sinir su: arama olmadan **hicbir dis olgu
dogrulanamaz**, yani bir sayfadan okunan fiyat da. Yalniz kendi icinde
aritmetikle kurulan konular gecer; yedek havuzdaki fiyat tabanli konularin
cogu gecmez. Kalici cozum arama (faturalandirma). Bu hata degil, bilincli
kapi: dogrulanamayan iddia videoya girmiyor. Bir deneme/test icin
`ALLOW_UNVERIFIED=5` + `private`. `python tools/gemini_check.py` (ya da Actions >
gemini-check) tabloda "arama" sutununda bunu gosterir.

## Tek dugme: AUTO_PRIVACY

GitHub > Settings > Secrets and variables > Actions > **Variables** >
`AUTO_PRIVACY`

| deger | ne olur |
|---|---|
| `public` (veya hic tanimlama) | uretilen her video herkese acik yuklenir |
| `unlisted` | linki olan gorur, aramada/akista cikmaz |
| `private` | sadece sen gorursun; sen secip Studio'dan acarsin |
| `off` | YouTube'a hic yuklenmez; video yine uretilir, release'e konur |

Bir sey ters giderse `off`. Kod degismiyor, bir sonraki kosudan itibaren gecerli.

## Elle tetikleme

Actions > daily > Run workflow:

- `script`: kuyruktaki belirli bir dosya
- `mode`: bu kosu icin yayin modu (`auto` = AUTO_PRIVACY)

`publish.yml` eski videoyu yeniden uretip yuklemek icin duruyor.

## Gemini'nin rolleri (`editorial/roles.py`)

> Daily bunlari **cagirmiyor** (8 Kasim). Bolum, kod geri baglanirsa diye duruyor.

| rol | is | kodun kontrolu |
|---|---|---|
| yapimci | 5 konu adayi, 4 bicim, kendi puani (arama destekli) | dogrulanabilirlik/merak/guvenlik < 7 elenir, tekrar elenir, bicim dengesi |
| yazar | senaryo; hook→why→data→turn→resolve | `rules.validate_script`: sahne, pose, sure, rol sirasi, yasakli kalip |
| editor | 5 puan + risk + her rakam icin formul + olay iddialari | puan < 7 ya da risk orta/yuksek = revize/ret; hikayede >= 2 olay iddiasi sart |
| dogrulayici | formulsuz rakamlari ve olay iddialarini canli aramayla kontrol | celisen = revize; dogrulanamayan en fazla `ALLOW_UNVERIFIED`; arama yoksa hepsi dogrulanamayan |
| sanat yon. | 8 temadan birini secer | bilinmeyen/son 3'te kullanilan reddedilir |
| metin yazari | 4 baslik + YouTube/Instagram/TikTok metni | `publish/manifest.py`: hashtag sayisi, link, emoji, kaynak bolumu |

Model adi sabit degil: `editorial/llm.py` her kosuda `ListModels`'e sorup
adaylari diziyor (en yeni kararli flash basta), sonra **kosunun basinda her
aday icin kucuk bir yoklama** (`warm`, 20 sn) atip ilk cevap vereni seciyor.
Bozuk model (503/zaman asimi) dinleniyor, kotasi olmayan ya da 404 veren
kosu boyunca eleniyor. Hicbiri cevap vermezse kosu hemen, nedenleriyle biter.
Anahtarin hangi modelleri calistirdigini gozle gormek icin: Actions >
**gemini-check** > Run workflow (arama destegi var mi, kac saniye, 429 nedeni).

**Editor yetmez, kod da hesaplar.** Editorden her ekran rakami icin bir
formul isteniyor (`0.40*60 = 24`); `safe_eval` onu hesaplayip Gemini'nin
yazdigi sonuclarla karsilastiriyor. Gemini "yayinla" dese bile aritmetik
tutmuyorsa yayinlanmaz.

## Dosyalar

```
editorial/   Gemini: llm.py (istemci) roles.py (istemler) rules.py (kurallar)
             pipeline.py (akis) signals.py (HN/GitHub/YouTube canli sinyal)
             authored.py (yazilmis senaryolarin kapisi, Gemini yok)
worker/      cizim: synth, draw, scenes, themes, byte, series_*, qc, build
publish/     youtube.py (yukleme) manifest.py (platform metinleri)
             instagram.py tiktok.py net.py ledger.py (content/social.json)
tools/       setup_runner.sh, fetch_voice.sh, pick_script.py, release.sh,
             check_token.py, get_refresh_token.py, gemini_check.py,
             host_video.sh (mp4'u media dalina koyar), tiktok_login.py
tests/       agsiz testler (sahte Gemini)
content/     scripts/ rejected/ plan.md backlog.json built.json published.json
ci/          .github/workflows'un kopyasi (asagiya bak)
```

## Testler

```bash
python -m unittest discover -s tests -v
```

Ag yok, Gemini yok, secret yok; saniyenin altinda biter. `check.yml` her
push'ta calistiriyor ve workflow YAML'larini da dogruluyor.

## Lokal render

```bash
pip install -r requirements.txt
bash tools/fetch_voice.sh en-us-ryan-high     # ~120 MB, repoda yok
python -m worker.build content/scripts/<id>.json
GEMINI_API_KEY=... python -m editorial --dry-run
```

## Secrets ve degiskenler

| ad | tur | nerede kullaniliyor |
|---|---|---|
| `GEMINI_API_KEY` | secret | editorial (senaryo yazimi) |
| `YOUTUBE_API_KEY` | secret | editorial/signals.py (YouTube trend aramasi) |
| `YOUTUBE_CLIENT_ID` | secret | yukleme |
| `YOUTUBE_CLIENT_SECRET` | secret | yukleme |
| `YOUTUBE_REFRESH_TOKEN` | secret | yukleme |
| `AUTO_PRIVACY` | **variable** | yayin modu (yukaridaki tablo) |
| `MIN_SCORE` | **variable** | editor esigi, 5-9, varsayilan 7 (kalite kadrani) |
| `GEMINI_MODEL` | **variable** | bos = otomatik en yeni kararli flash; gemini-check tablosunda **evet** diyen ilk modeli sabitle (ornek: `gemini-3.6-flash`); her kosunun basinda asiri yuklu yeni modelleri yoklayip vakit kaybetmez. Bozulursa yine otomatik listeye duser. Not: `gemini-2.5-*` ve `2.0-*` yeni hesaplarda 404, onlari sabitleme |
| `ALLOW_UNVERIFIED` | **variable** | aramayla dogrulanamayan en fazla kac iddia kabul, 0-5, varsayilan 1 |
| `INSTAGRAM_USER_ID` | secret | Instagram Reels yukleme (hesap numarasi) |
| `INSTAGRAM_TOKEN` | secret | uzun omurlu Instagram token'i (60 gun; haftalik otomatik yenilenir) |
| `TIKTOK_CLIENT_KEY` | secret | TikTok uygulamasi |
| `TIKTOK_CLIENT_SECRET` | secret | TikTok uygulamasi |
| `TIKTOK_REFRESH_TOKEN` | secret | `python tools/tiktok_login.py` verir (365 gun; her kullanimda yenilenir) |
| `GH_PAT` | secret | **istege bagli ama uzun vadede gerekli**: yenilenen token'lari secret'a geri yazar (asagiya bak) |
| `AUTO_INSTAGRAM` | **variable** | `off` = Instagram adimini atla |
| `AUTO_TIKTOK` | **variable** | `off` = TikTok adimini atla |

**OAuth onay ekrani "In production" olmali.** "Testing" modunda Google
refresh token'i 7 gunde iptal ediyor: ilk hafta calisir, sekizinci gun
yuklemeler durur.

## Instagram ve TikTok

Ikisi de **yalniz `AUTO_PRIVACY=public`** iken ve secret'lari varsa calisir;
`private` denemelerde bir sey gondermezler. Ayni video ayni platforma iki
kez gitmez (`content/social.json`).

**Instagram** (resmi "Instagram API with Instagram Login", kendi hesabin
icin uygulama incelemesi gerekmiyor). Hesap *Professional* (Creator) olmali.
Instagram videoyu kendi cekiyor, bu yuzden mp4 herkese acik bir adreste
durmali: `tools/host_video.sh` videoyu `media` dalina koyar (tek commit,
son 8 video kalir), GitHub Pages adresi `https://<kullanici>.github.io/byte-shorts/<id>.mp4`
olur, dosya gercekten inene kadar bekler. Sonra konteyner olusur, Meta isleyene
kadar durum sorgulanir, `media_publish` ile yayinlanir.

Kurulum (bir kerelik): 1) hesabi Professional'a cevir, 2) developers.facebook.com'da
uygulama > Instagram urunu > hesabini ekle > uzun omurlu token uret,
3) `INSTAGRAM_USER_ID` ve `INSTAGRAM_TOKEN` secret'lari, 4) Actions >
**media-init** calistir (bos `media` dalini kurar), 5) Settings > Pages >
Source: `media` dali, kok klasor. Kontrol: `python -m publish.instagram --check`.

**TikTok** (resmi Content Posting API, *inbox upload*). Denetimsiz uygulamalar
dogrudan yayinlayamiyor; video hesabinin **gelen kutusuna taslak** olarak
yuklenir, sen TikTok uygulamasinda acip aciklamayi yapistirip "Paylas"a
basarsin (API aciklama koymaya izin vermiyor; metin Release'teki
`captions.md` icinde). Kurulum: developers.tiktok.com'da uygulama (platform
Desktop, redirect URI tam olarak `http://127.0.0.1:8765/callback/`, Login
Kit + Content Posting API, `video.upload` izni), sonra bilgisayarinda
`python tools/tiktok_login.py` (key/secret terminalde sorulur, sohbete
yazilmaz), cikan token'i `pbcopy < ~/.byte-tiktok-refresh-token` ile panoya
alip GitHub'da `TIKTOK_REFRESH_TOKEN` secret'ina yapistir. Uygulama
"sandbox/test" durumundaysa kendi hesabini test kullanicisi olarak eklemen
gerekebilir; TikTok bunu portalda gosterir.

**Token omru ve `GH_PAT`.** `GITHUB_TOKEN` secret yazamaz. Instagram token'i
60 gunde, TikTok access token'i 24 saatte biter; TikTok her yenilemede yeni
refresh token verebilir. Bunlari secret'a geri yazmak icin fine-grained bir
token gerekir: GitHub > Settings > Developer settings > Fine-grained tokens,
yalniz bu repo, izin **Secrets: Read and write**; secret adi `GH_PAT`.
`GH_PAT` yoksa kosu bozulmaz ama yenilenen token kaybolur: Instagram 60.
gunde, TikTok refresh token'i degistiyse ilk bozulmada durur. `tokens.yml`
her pazartesi Instagram token'ini yeniler.

## Workflow dosyalari neden iki yerde

`.github/workflows/*.yml` asil dosyalar. `ci/` altindaki kopyalar, bazi
araclarin `.github/` klasorune yazamamasi yuzunden duruyor; degisiklik
yaparken ikisini de guncelle ya da `cp ci/*.yml .github/workflows/`.

## Sorun giderme

| belirti | sebep | cozum |
|---|---|---|
| kosu kirmizi, "Kuyruk bos" (~15 sn) | `content/scripts` icinde islenmemis senaryo kalmadi | yeni parti yaz (`content/plan.md`'deki siradaki 10 satir), `python -m editorial.authored`, push |
| kosu kirmizi, "BUGUN VIDEO YOK" | eski Gemini yolundan kalma; daily artik Gemini'yi cagirmiyor | `ci/daily.yml` ile `.github/workflows/daily.yml` ayni mi? (`cp ci/*.yml .github/workflows/`; `tests/test_daily.py` bunu denetler) |
| "youtube secrets gecersiz" | token iptal / client uyusmuyor | `python tools/check_token.py`, sonra secrets'i guncelle |
| "UYARI: public istendi, YouTube private yapti" | API projesi dogrulanmamis | videoyu Studio'dan elle public yap; Google'a API denetimi basvurusu |
| Actions "startup failure" | GitHub faturalandirma kilidi | Settings > Billing > odeme yontemi ekle |
| Gemini 404 | model adi emekli | kendiliginden siradakine gecer; `GEMINI_MODEL` ile zorlayabilirsin |
| "konu uret" uzun suruyor | Gemini modelleri 503 (asiri yuklu) ya da zaman asimi veriyor | saglikli kosu 2-4 dk. Bozuk model: hic cevap vermemis modele ilk istek 45 sn, zaman asiminda hemen sonrakine; 503'te 2 tekrar; 5 dk dinlenir (sonraki roller ona gitmez); tum Gemini asamasi 10 dk (`GEMINI_DEADLINE`), adim 12 dk. Dolunca "BUGUN VIDEO YOK" ile kirmizi biter. Hizli cozum: gemini-check'in saglikli dedigi bir modeli `GEMINI_MODEL` olarak sabitle |
| Gemini 429 | kota/hiz siniri | log nedenini yazar: "bu anahtarda kotasi yok" ve "gunluk kota" modeli hemen eler, "hiz siniri" Google'in istedigi sure kadar bekler (en fazla 65 sn, toplam `GEMINI_WAIT_BUDGET` = 240 sn). Hicbir model cevap vermezse log sonunda her modelin nedeni tek satirda |
| Instagram adimi uyari verdi, "hazir olmadi / ERROR" | Meta videoyu isleyemedi ya da Pages adresi henuz acik degil | `media-init` calisti mi, Pages `media` dalinda mi; video 1080x1920 H.264 mp4. Elle: `python -m publish.instagram out/<id>/manifest.json --video-url <adres>` |
| Instagram "Invalid OAuth / token" | token suresi doldu ya da yenilenemedi | Meta panelinden yeni uzun omurlu token uret, `INSTAGRAM_TOKEN` guncelle; `GH_PAT` kur ki bir daha olmasin |
| TikTok "scope_not_authorized" | uygulamada `video.upload` yok | portalda Content Posting API'yi ekle, `tiktok_login.py`'yi tekrar calistir |
| TikTok "invalid_grant" | refresh token iptal / degismis | `tiktok_login.py`'yi tekrar calistir, secret'i guncelle |
| "arama araci kullanilamiyor" / "web search is unavailable" | Google Search grounding **ucretsiz Gemini anahtarinda yok** (resmi fiyat sayfasi: Free = Not available) | Kod bunu kendisi anlar: ilk 429/400'de ayni modele aramasiz sorar, o kosuda aramayi birakir ve hikaye/gundem adaylarini bastan eler; yalniz formullu (`measured`) konular yayina girer. Hikaye/gundem acmak icin AI Studio'da projeye faturalandirma bagla: ucretli katmanda ayda 5.000 arama bedava (Gemini 3+ modelleri icin ortak), sonrasi 1.000 aramaya 14 USD. Bir kosu en fazla birkac arama yapar. Kullandikca token ucreti de yazilir; AI Studio'da butce uyarisi koy |

## brand.json

Isim, handle, aciklama altbilgisi, hashtag'ler, baslik kurallari. Handle
degisirse burasi degisiyor; kapanis kartina da buradan giriyor.
