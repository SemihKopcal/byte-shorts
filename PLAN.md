# BYTE — yol haritası

Bu dosya "ne yapılacak"ı tutuyor. Her madde bittiğinde işaretlenecek.
Kararların **sebebi** de burada; altı ay sonra "neden böyle yapmıştık" diye
sorduğumuzda cevap kodun içinde değil burada olsun.

---

## Durum (6 Kasım 2026)

**Çalışıyor:** Piper sesi, 9 sahneli katalog, 8 tema, kapalı döngü
(Gemini yazar → editör yargılar → kod aritmetiği hesaplar → render → QC →
YouTube → defter → release). Günde 2 video, `AUTO_PRIVACY` değişkeniyle tek
düğmeli yayın kontrolü.

**Sırada (öncelik sırasıyla):**

1. BYTE anlatıcı (aşağıda madde 1): `draw_byte_pointing` yazıldı, sahnelere
   bağlanmadı.
2. Animasyonlu arka plan (madde 2): mesh/ızgara/halka animasyonları için bir
   taslak yazıldı ama henüz repoda değil; önce BYTE anlatıcı bitecek.
3. Instagram + TikTok: şimdilik release'ten elle; API otomasyonu 5-7 video
   sonra (bkz. "BYTE Instagram ve TikTok" artifact'ı).
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

## 6. Panel  ·  ⬜

GitHub arayüzü şu an panelin yerini tutuyor ama günlük iş için ağır.

- [ ] Onay kutusu: video oynat → "yayınla" / "atla" / "başlığı düzelt"
- [ ] Kuyruk: sıradaki senaryolar, düzenlenebilir
- [ ] Ölçüm: yayınlananların performansı

Bu en sona kalıyor — hat çalışmadan panel yapmak boş iş.

---

## 7. Diğer platformlar  ·  ⬜

- [ ] TikTok: hesap + handle (kurulum artifact'ında 09. bölüm)
- [ ] TikTok Content Posting API denetim başvurusu
- [ ] Instagram Reels: `instagram_content_publish` inceleme başvurusu
- [ ] Onay gelene kadar ikisine de elle yükleme (aynı dosya, 1080×1920)

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
