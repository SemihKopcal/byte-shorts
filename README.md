# byte-shorts

BYTE kanalinin uretim hatti. Gunde 2 video, hepsi kodla ciziliyor, konuyu
Gemini seciyor, YouTube'a kendiliginden yukleniyor.

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
```

## Gunluk akis (`daily.yml`, 04:15 ve 13:15 UTC)

1. Kuyruk bossa (ya da `topic` verildiyse) Gemini yeni senaryo yazar.
2. Editor kapisindan gecemeyen konu **yazilmaz**; nedeni `content/rejected/`
   altina duser. Hicbiri gecmezse kosu kirmizi biter: "bugun video yok",
   kotu video yayinlamaktan iyidir.
3. Video cizilir, `worker/qc.py` kontrol eder (sure, en-boy, ses, tekrar,
   kaynak, yayin metni).
4. `AUTO_PRIVACY` ne diyorsa o gizlilikle YouTube'a yuklenir.
5. `content/built.json` ve `published.json` repoya geri yazilir.
6. Video + Instagram/TikTok metinleri bir GitHub Release'e konur
   (telefondan indirilebilir).

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

- `topic`: "Gemini su konuyu yazsin" (bos = kendi secer)
- `script`: kuyruktaki belirli bir dosya
- `mode`: bu kosu icin yayin modu (`auto` = AUTO_PRIVACY)

`publish.yml` eski videoyu yeniden uretip yuklemek icin duruyor.

## Gemini'nin rolleri (`editorial/roles.py`)

| rol | is | kodun kontrolu |
|---|---|---|
| yapimci | 5 konu adayi, 4 bicim, kendi puani (arama destekli) | dogrulanabilirlik/merak/guvenlik < 7 elenir, tekrar elenir, bicim dengesi |
| yazar | senaryo; hook→why→data→turn→resolve | `rules.validate_script`: sahne, pose, sure, rol sirasi, yasakli kalip |
| editor | 5 puan + risk + her rakam icin formul + olay iddialari | puan < 7 ya da risk orta/yuksek = revize/ret; hikayede >= 2 olay iddiasi sart |
| dogrulayici | formulsuz rakamlari ve olay iddialarini canli aramayla kontrol | celisen = revize; dogrulanamayan en fazla `ALLOW_UNVERIFIED`; arama yoksa hepsi dogrulanamayan |
| sanat yon. | 8 temadan birini secer | bilinmeyen/son 3'te kullanilan reddedilir |
| metin yazari | 4 baslik + YouTube/Instagram/TikTok metni | `publish/manifest.py`: hashtag sayisi, link, emoji, kaynak bolumu |

Model adi sabit degil: `editorial/llm.py` her kosuda `ListModels`'e sorup
o anahtarla cagirilabilen en yeni kararli flash'i seciyor; calismayana
(404/kota) siradakine geciyor.

**Editor yetmez, kod da hesaplar.** Editorden her ekran rakami icin bir
formul isteniyor (`0.40*60 = 24`); `safe_eval` onu hesaplayip Gemini'nin
yazdigi sonuclarla karsilastiriyor. Gemini "yayinla" dese bile aritmetik
tutmuyorsa yayinlanmaz.

## Dosyalar

```
editorial/   Gemini: llm.py (istemci) roles.py (istemler) rules.py (kurallar)
             pipeline.py (akis) signals.py (HN/GitHub/YouTube canli sinyal)
worker/      cizim: synth, draw, scenes, themes, byte, series_*, qc, build
publish/     youtube.py (yukleme) manifest.py (platform metinleri)
tools/       setup_runner.sh, fetch_voice.sh, pick_script.py, release.sh,
             check_token.py, get_refresh_token.py
tests/       agsiz testler (sahte Gemini)
content/     scripts/ rejected/ backlog.json built.json published.json
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
| `ALLOW_UNVERIFIED` | **variable** | aramayla dogrulanamayan en fazla kac iddia kabul, 0-5, varsayilan 1 |

**OAuth onay ekrani "In production" olmali.** "Testing" modunda Google
refresh token'i 7 gunde iptal ediyor: ilk hafta calisir, sekizinci gun
yuklemeler durur.

## Workflow dosyalari neden iki yerde

`.github/workflows/*.yml` asil dosyalar. `ci/` altindaki kopyalar, bazi
araclarin `.github/` klasorune yazamamasi yuzunden duruyor; degisiklik
yaparken ikisini de guncelle ya da `cp ci/*.yml .github/workflows/`.

## Sorun giderme

| belirti | sebep | cozum |
|---|---|---|
| kosu kirmizi, "BUGUN VIDEO YOK" | Gemini 3 konuda da editor kapisindan gecemedi | `content/rejected/` icindeki dosyada nedeni yazar |
| "youtube secrets gecersiz" | token iptal / client uyusmuyor | `python tools/check_token.py`, sonra secrets'i guncelle |
| "UYARI: public istendi, YouTube private yapti" | API projesi dogrulanmamis | videoyu Studio'dan elle public yap; Google'a API denetimi basvurusu |
| Actions "startup failure" | GitHub faturalandirma kilidi | Settings > Billing > odeme yontemi ekle |
| Gemini 404 | model adi emekli | kendiliginden siradakine gecer; `GEMINI_MODEL` ile zorlayabilirsin |
| Gemini 429 | kota/hiz siniri | log nedenini yazar: "bu anahtarda kotasi yok" ve "gunluk kota" modeli hemen eler, "hiz siniri" Google'in istedigi sure kadar bekler (en fazla 65 sn, toplam `GEMINI_WAIT_BUDGET` = 480 sn). Hicbir model cevap vermezse log sonunda her modelin nedeni tek satirda |
| "dogrulanamayan ... web search is unavailable" | arama destegi (grounding) bu anahtarda/modelde yok | yalniz formullu konular gecer; hikaye icin AI Studio'da anahtarin arama kotasini kontrol et |

## brand.json

Isim, handle, aciklama altbilgisi, hashtag'ler, baslik kurallari. Handle
degisirse burasi degisiyor; kapanis kartina da buradan giriyor.
