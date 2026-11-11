# byte-shorts

BYTE kanalinin uretim hatti. Gunde 2 video (ilk 30 gun, A/B testiyle; veri gelince 4'e cikilabilir), hepsi kodla ciziliyor, konular
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

## Gunluk akis (`daily.yml`, 04:15 ve 16:15 UTC)

1. `content/scripts/` icindeki siradaki islenmemis senaryo alinir (asagida
   "Yazilmis senaryolar"). Bu, kosunun **ilk isi**: ffmpeg/font/pip/ses modeli
   kurulumundan once. Gemini yok, API anahtari gerekmez.
2. Kuyruk bossa kosu ~15 saniyede **kirmizi** durur ("Kuyruk bos"), hicbir sey
   kurulmaz, dakika yanmaz; yeni parti yazilana kadar her kosu boyle biter.
   Kuyrukta 12 ya da daha az senaryo kalinca uyari yazar (kirmizi degil).
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

**Kuyruk sirasi.** Varsayilan sira dosya adi sirasidir. `content/order.json` (id
listesi) varsa listedeki islenmemis senaryolar liste sirasiyla, hepsinden once alinir;
listede olmayanlar dosya adi sirasiyla arkasindan gelir. Dosya yoksa ya da bozuksa
hicbir sey degismez. Listeyi A/B testinde kollari dizmek icin kullaniyoruz.

## A/B testi (`content/experiments.json`, `tools/ab_report.py`)

Hangi videolar ne kadar tutuyor? `experiments.json` her deneyin kollarini (senaryo
id'leri), ana olcutu ve en az video sayisini tutar; su an `e1-length` (kisa ~25 sn
karsi standart ~36 sn, 7 + 7 video, plan: `content/plan.md`). Yayindan en az 72 saat
sonra YouTube Studio'dan Analytics > Advanced mode > Content > disa aktar (CSV);

```bash
python tools/ab_report.py studio.csv                  # tum deneyler + "ne tutuyor" tablosu
python tools/ab_report.py studio.csv --exp e1-length --md rapor.md
python tools/ab_report.py --status                    # hangi video uretildi, YouTube kimligi
```

Video <-> senaryo eslestirmesi YouTube kimligiyle (`published.json` ya da
`--map {"senaryo-id": "youtube-id"}`), olmazsa baslikla yapilir; Studio'nun
Turkce ya da Ingilizce sutun adlari taninir, taninmazsa `--col views=<sutun adi>`.
Panel modunda `published.json` guncellenmedigi icin eslestirme cogu zaman baslikla
olur. Rapor kucuk n'de dogru olsun diye siralama (Mann-Whitney) permutasyon testi
kullanir; kol basina 7 videoyla yalniz buyuk farklar "belirgin" cikar.

Kuyruk 100 senaryoda biter: gunde 1 videoyla 100 gun, gunde 2 videoyla 50 gun, gunde 4 videoyla 25 gun.
Bitince daily "Kuyruk bos" diye kirmizi durur (Gemini'ye dusmez); yeni parti
zamaninda yazilmali. Kuyruk sirasi dosya adi sirasidir, bu yuzden `pNNN-`
numarasi plandaki siradir.

## Video stili: kamera, gecis, doku, tempo (`brand.json` > `style`, `worker/style.py`)

Tema rengi her videoda degisiyordu ama gerisi ayniydi (ayni yavas yakinlasma, ayni gecis, ayni
tempo). Artik her videonun kendi "el yazisi" var. Hepsi senaryo kimliginden (sha256) turetilir:
rastgele DEGIL, `publish.yml` videoyu yeniden urettiginde iki render birebir ayni cikar; ayni
senaryo hep ayni gorunur, farkli senaryolar farkli.

| Ne | Secenekler | Nasil |
|---|---|---|
| Kamera (sahne basina) | yakinlas, uzaklas, saga kay, sola kay, yukari kay | art arda iki sahne ayni hareketi yapmaz; kayma kenardan tasmaz |
| Gecis efekti | flas, yatay kayma, titresim, odak, zipla | videonun iki "imza" efekti var, sahne degisimlerinde sirayla (0,3 sn) |
| Doku | temanin kendi dokusu ya da baska bir doku | %50 / %50 |
| Tempo | hikaye biraz yavas, olcum capcanli, aciklama arada | konusma +-%3, beat arasi bosluk 0,9-1,12x |

Tempo uzarsa (56 sn'yi asarsa) `worker/build.py` varsayilan tempoya doner; QC 59 sn'de durur.
Kapatmak icin `brand.json` > `style` > `"enabled": false` (eski gorunum). Algoritmayi degistirirsen
`style.VERSION`'i artir: butun videolarin gorunumu degisir, bilerek yapilmali.

## Karton / cizgi film stili (`brand.json` > `cartoon`, `worker/cartoon.py`)

Aciklayici cizgi film kanallarinin teknigi, BYTE'in kendi cizimiyle: kod cizer, stok gorsel ve baska
kanalin karakteri yok. Dikey Short, yalniz senaryodan okuyan seri (G); A/B serileri eski gorunumde kalir.

| Ne | Nasil |
|---|---|
| Iki yuz | acik **kagit** ve koyu **lacivert** (`themes.TOON_THEMES`); sahneler arasinda sirayla, hangisiyle basladigi senaryo kimliginden |
| BYTE sunucu | sol ustte kalin dis cizgili cikartma (`byte.draw_byte_sticker`); imleci SESIN siddetiyle oynar (dudak senkronunun karsiligi), fosforlu kelime belirirken kolunu uzatir |
| Fosforlu kelime | ust bantta (sahneler 330 px'ten basliyor) soldan saga boyanir. **Cumle basina**: beat'e `"kw": "metin"` yazilirsa o cumle okunurken (basladiktan 0,3 sn sonra) belirir, cumle bitince kapanir; `""` = bu beat'te otomatik kelime yok. `kw` ayni beat'in `cap` alanindan BIREBIR bir parca, en fazla 18 karakter, harf/rakam/`. , % $ + - x : ? !` olmali (`editorial/rules.py` kapida kontrol eder; Fredoka'da olmayan glif bos kutu cikar). Otomatik yalniz sahnenin ilk beat'inde ve yalniz `title` (kicker) ile etiketli sahnelerde: `counter`/`equation`/`contrast` ana sayiyi zaten dev yaziyor, tekrar etmez. Gemini yazarken 4-7 beat'e koyar (`editorial/roles.py`), kuyruktaki p005-p037'ye elle eklendi |
| Elle cizilen isaret | beat'e `"mark": "check"` ya da `"x"` (yalniz `kw` ile birlikte; videoda en fazla 2) -> kelimenin yaninda kalemle cizilir |
| Gecis | sahne degisiminde iris (daire acilir, kalin halka); eski FX gecisleri (flas/kayma/titresim) bu modda kullanilmaz, kamera hareketi kalir |
| Altyazi | krem hap, kalin cizgi, sert golge; aktif kelime fosforlu. Font: Fredoka One (SIL OFL, `worker/assets/`) |

Hepsi senaryo kimliginden turetilir (sha256), rastgele DEGIL: `publish.yml` videoyu yeniden uretse de iki
render birebir ayni.

**Acma/kapama** (`brand.json` > `cartoon`): `enabled` (true/false), `share` (0-1: videolarin ne kadari karton
olsun, geri kalani eski koyu gorunum; kimlikten turetilir), `alternate` (false = sahneler hep kagit).
Kapatinca bir sonraki render eski gorunumle cikar; gecmis videolar etkilenmez.

**Bilmen gerekenler:** (1) render ~7x gercek zaman (29 sn'lik video ~3,5 dk, 2 cekirdekli runner) -- eski
gorunumden yavas; `daily` zaman asimi icinde. (2) Tema sahne basina degistigi icin sahneler `D.INK`/`D.TONE`/
`D.PANEL` gibi tema degerlerini CAGRI ANINDA okumali; sahneye sabit renk yazma (`tests/test_cartoon.py` koyu
temalarin eski degerlerini ve iki yuzun okunurlugunu kilitliyor). (3) Yeni sahne turunde BYTE cizeceksen
`draw_byte` degil `D.byte` kullan: karton temasinda dis cizgi ekler, yoksa lacivertte koyu govde kaybolur.
Algoritmayi degistirirsen `cartoon.VERSION`'i artir.

## Begen / takip CTA'si (`brand.json` > `cta`, `worker/cta.py`)

Videolarin sonunda sakin ve kisa bir "begen, takip et" cagrisi var; hepsini hat ekler,
senaryoya yazilmaz (`editorial/rules.py` senaryo metnindeki "subscribe / like and / follow
us" kaliplarini hala yasaklar, yoksa iki kez soylenirdi). Dort yerde gorunur:

1. **Kapanis karti + ses:** son sesli cumle ("Like it, and follow Byte for more.") ve
   `LIKE` / `FOLLOW BYTE` chip'leri; chip'ler cumle baslayinca cikar, sirayla "basilir"
   (dolar), BYTE sagi gosterir (Shorts'un dugmeleri sagda). Kapanista altyazi zaten kapali.
2. **Kose etiketi:** videonun ~%42'sinde 2.6 sn sol ustte kucuk `LIKE · FOLLOW`. Kapanis
   kartiyla ya da ilk 3 sn ile cakisacaksa hic cikmaz.
3. **Aciklama:** platforma ozel satir (YouTube "Subscribe", Instagram/TikTok "Follow
   @handle"); ilk paragrafin arkasina, TikTok'ta hashtag'lerden once. TikTok 300 karakteri
   asacaksa eklenmez.
4. **Sabitlenecek yorum:** `captions.md` ve `manifest.json > cta.pinned_comment`. YouTube API
   yorum sabitlemeye izin vermiyor: yayindan sonra elle yaz, uc nokta > Sabitle.

**Hangi videoda?** Karar yalniz senaryoya ve depodaki dosyalara bagli (id, seri `G`, son
beat `close`, `brand.json`, `content/experiments.json`); zamana ya da `built.json`'a
bagli degil. `publish.yml` bazi akislarda videoyu yeniden uretiyor ve iki render birebir
ayni cikmali. A/B deneyindeki videolar da CTA'li: iki kola da ayni +~3 sn eklenir ve
deneyin ana olcutu `stayed` (ilk saniyelerde kaydirmama) videonun sonundan etkilenmez.
Kol uzunluklari buna gore ~28 sn / ~39 sn olur. Deney videolarini CTA'siz tutmak
istersen `skip_experiment_scripts: true` yap. Kapatmak icin `"enabled": false`; metinler ve
zamanlama ayni blokta. Uyari: sesli cumlede "Byte" yaz (Piper "BYTE"i harf harf okur).
CTA'li video ~3 sn uzar; `editorial.authored` kapisi 52 sn'de durur, QC 59 sn'de.

**Video sonu:** video, son kelimeden 0,45 sn sonra biter (`worker/synth.py` `END_PAD`);
eskiden 0,18 sn once bitiyor ve son kelimenin sonu kesiliyordu.

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
worker/      cizim: synth, draw, scenes, themes, byte, series_*, qc, build, cartoon (karton stili), assets/ (font)
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

Ag yok, Gemini yok, secret yok; birkac saniyede biter. `check.yml` her
push'ta calistiriyor ve workflow YAML'larini da dogruluyor.

## Canliya alma akisi (CI/CD)

Hicbir sey `main`'e dogrudan gitmesin; once PR'da kontrol edilir. `main`'e girdigi
an GitHub tarafindaki workflow'lar (`daily`, `panel-publish` ...) canli olur. Panel
SUNUCUSU ise ayrica, elle guncellenir (adim 4).

1. **Dal ac, push'la, PR ac:** `git switch -c ozellik && git push -u origin ozellik`
2. **PR'daki kontroller** (hepsi yesil olmadan birlestirme):

   | Kontrol | Ne bakar |
   |---|---|
   | `check / test` | birim testleri, senaryo kapisi, workflow YAML, shellcheck, **secret taramasi** |
   | `check / panel` | panelin kendi testleri |
   | `check / docker` | panel imaji derlenir, aga cikissiz/salt okunur/yetkisiz konteynerde acilir, compose dosyasi dogrulanir |
   | `render-smoke` | `worker/`, `requirements.txt` ya da workflow degisince **gercek bir video** uretilir (ses + kareler + ffmpeg + QC). PR'dan mp4 artifact'ini indirip izleyebilirsin |

3. **Birlestir** (Squash and merge). Workflow degisiklikleri hemen canli olur.
4. **`panel/` degistiyse** sunucuda: `cd /srv/www/byte/app/panel/deploy && ./update.sh`
   (yedek alir, derler, saglik bekler, saglikli degilse kendiliginden geri alir;
   ayrintisi `panel/deploy/README.md` bolum 11). Yalniz icerik/workflow degistiyse
   sunucuda yapilacak bir sey YOK.
5. **Ilk kez deneme:** Actions > daily > Run workflow, panelde videoyu izle. Panelde
   Ayarlar > YouTube gizliligini once `private` yap, YouTube Studio'da gor, sonra `public`.

**Dependabot PR'lari** (haftalik, hicbiri kendiliginden birlesmez): birer birer, `check`
yesilken birlestir. `numpy`, `Pillow`, `piper-tts` ve Actions surum atlamalari (`checkout`,
`cache`, `setup-python`, `upload-artifact`) videoyu/hatti etkiler: `render-smoke` yesil olmali
ve artifact'taki mp4'u bir kez izlemelisin. `Pillow`/`numpy` PR'inda `check.yml`'deki satir ici
surumu de ayni surume cek (test seni uyarir).

**Neden `main`'e dogrudan koruma kurali koymuyoruz:** `daily` bot'u her kosu sonunda
`main`'e dogrudan commit atiyor (defter). "Require status checks" ya da "Require pull
request" kurali bu push'u reddeder ve uretim durur. PR disiplini gonullu.

**Guvenlik duvarlari** (hepsi `tests/` ile kilitli, biri bozulursa test kirmizi olur):
`check`/`render-smoke` secret gormez ve depoya yazamaz (fork PR'lari da guvenle calisir);
sirli workflow'lar yalniz zamanlayici ya da elle calisir, push/PR ile asla; yalniz
GitHub'in kendi `actions/*` action'lari kullanilir; her workflow izinlerini bildirir;
sirlar `echo` edilmez; depoda token/anahtar bulunursa (`tools/secret_scan.py`) CI kirmizi olur;
panel konteyneri port yayinlamaz, root degildir, salt okunurdur.

**Bilinen artik risk:** `ffmpeg` ikilisi `tools/setup_runner.sh` ile BtbN'nin "latest"
surumunden iniyor ve `daily` kosusunda calisiyor (sabitlenmis degil: o proje eski surumleri
tutmuyor). Ele gecirilirse `daily`'nin `contents: write` yetkisi riske girer. Azaltma plani:
render'i sirsiz/yazmasiz ayri bir job'a bolmek (bkz. `PLAN.md`).

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

Isim, handle, aciklama altbilgisi, hashtag'ler, baslik kurallari, begen/takip CTA'si
(`cta`, yukaridaki bolum). Handle degisirse burasi degisiyor; kapanis kartina da buradan giriyor.

## Panel (byte.semihkopcal.com)

Videoları görmek, onaylamak, takvime koymak ve servislerin sağlığını izlemek için bir
panel var. Kod `panel/`, kurulum ve işletme rehberi `panel/deploy/README.md`. Video üretimi
yine GitHub Actions'ta; `PANEL_MODE=on` değişkeniyle `daily` videoyu yayınlamak yerine R2'ye
koyar, yayını panel `panel-publish` workflow'uyla yönetir.

**Takvim:** panelde ay ızgarası (Türkiye saati) hangi videonun ne zaman yayınlanacağını,
geçmiş/tahmini üretimleri, A/B deney kollarını ve kuyruğun kaç güne yettiğini gösterir.
Güne tıklayıp video+saat seçerek ya da yayını başka güne sürükleyerek planlanır; ayrıca
otomatik doldurma ve haftalık saat şablonu var. Ayrıntı: `panel/deploy/README.md` §10.
