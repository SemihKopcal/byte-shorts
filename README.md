# byte-shorts

BYTE kanalinin uretim hatti. Gunde 2 video, hepsi kodla ciziliyor.

Kural: **hicbir video senin onayin olmadan yayina cikmaz.** `daily.yml`
sadece uretir ve artifact birakir; `publish.yml` elle tetiklenir.

---

## Nasil calisiyor

```
content/scripts/*.json          senaryo (beat'ler, veriler, kaynaklar)
        |
        v  worker/synth.py      Piper ile beat beat seslendirme
                                -> her cumlenin baslangic/bitis saniyesi KESIN
        |
        v  worker/series_*.py   sahneler; kesmeler beat sinirlarina oturuyor
        |
        v  worker/build.py      Pillow -> ham RGB -> ffmpeg (ara dosya yok)
        |
        v  worker/qc.py         sure, en-boy, ses seviyesi, tekrar, kaynak
        |
        v  publish/youtube.py   varsayilan PRIVATE
```

Sahne kesmeleri sabit bir sayaca degil **seslendirme beat'lerine** bagli.
Sabit sayac slideshow demek, slideshow da YouTube'un Temmuz 2026
"sablon icerik" maddesinin tam tanimi.

---

## Lokal calistirma

```bash
sudo apt-get install -y ffmpeg fonts-inter    # macOS: brew install ffmpeg
pip install -r requirements.txt
bash tools/fetch_voice.sh en-us-ryan-high     # ~120 MB, repoda yok

python -m worker.build content/scripts/2026-10-27-cost-of-alphabets.json
# -> out/<id>/<id>.mp4 + manifest.json
```

`--skip-synth` seslendirmeyi atlar (timeline.json varsa) -- sadece cizimde
oynarken kullan, her seferinde 40 saniye kazandiriyor.

> **Font**: Inter kurulu degilse `draw.py` hata firlatiyor, sessizce baska
> fonta dusmuyor. Bilerek boyle -- sessiz font degisimi videoyu gorunmeden
> bozar, ve ancak izlerken fark edersin.

---

## Seri ekleme

`worker/series_c.py` ac, `draw.py`'dan import et, en altta `STAGES` tanimla:

```python
STAGES = [("b1", "b2", scene_hook),
          ("b3", "b9", scene_table),
          ("b15", None, scene_close)]   # None = videonun sonuna kadar
```

Senaryoda `"series": "C"` yazdigin an `build.py` modulu kendi buluyor.
Seriler birbirini import etmiyor; ortak olan her sey `draw.py`'da.

---

## Senaryo formati

```jsonc
{
 "id":     "2026-11-03-...",     // essiz; published.json buna bakiyor
 "series": "B",
 "title":  "...",                 // <= 60 karakter, clickbait yok
 "sources": ["..."],              // ekranda sayi varsa ZORUNLU
 "beats": [
   {"id": "b1",
    "say": "three dollars",       // TTS'in okuyacagi
    "cap": "$3"}                  // ekranda gorunecek
 ]
}
```

`say` ile `cap` ayri olmak zorunda: TTS'e `$3` yazarsan "dolar uc" der,
ekrana `three dollars` yazarsan amator duruyor.

---

## Workflow'lar

| dosya | ne zaman | ne yapar |
|---|---|---|
| `daily.yml` | 04:15 ve 13:15 UTC + elle | siradaki scripti uretir, artifact birakir. **Yuklemez.** |
| `publish.yml` | sadece elle | yeniden uretir, QC'den gecirir, YouTube'a yukler |

Cizim deterministik oldugu icin `publish.yml` artifact'i indirmek yerine
yeniden uretiyor: artifact suresi (2 gun) dolsa bile yayinlayabiliyoruz ve
QC bir kez daha calisiyor.

**Artifact kotasi**: ucretsiz hesapta 500 MB. Video ~39 MB, gunde 2 tane.
`retention-days: 2` bu yuzden var; dusurursen eski kosulari kaybedersin,
yukseltirsen kota dolar ve yeni kosular artifact birakamaz.

---

## Secrets

| isim | nereden | ne zaman |
|---|---|---|
| `YOUTUBE_CLIENT_ID` | Google Cloud -> Credentials | publish |
| `YOUTUBE_CLIENT_SECRET` | ayni | publish |
| `YOUTUBE_REFRESH_TOKEN` | `tools/get_refresh_token.py` | publish |

`daily.yml` hicbirini istemiyor -- uretim tamamen offline. Secrets sadece
yayin adiminda okunuyor.

**OAuth onay ekrani "In production" olmali.** "Testing" modunda Google
refresh token'i 7 gunde bir gecersiz kiliyor: ilk hafta her sey calisir,
sekizinci gun yuklemeler sessizce durur.

---

## Kota

`videos.insert` ayri bir "Video Uploads" kovasindan **gunde 100 cagri**.
Gunde 2 video icin fazlasiyla yeterli. Basarisiz denemeler de bu kovadan
dustugu icin `publish/youtube.py` 4xx hatalarinda tekrar denemiyor.

---

## brand.json

Isim, handle, aciklama altbilgisi, hashtag'ler ve baslik kurallari tek
dosyada. Handle degisirse burasi degisiyor, baska hicbir yer degil.
