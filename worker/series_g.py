"""
Genel seri -- sahneleri senaryodan okur.

series_a/series_b her sahneyi elle yazilmis bir fonksiyona bagliyor; yeni konu
= yeni Python dosyasi. Burada tersi: senaryo her beat icin katalogdan bir
sahne ADI ve o sahnenin data'sini veriyor, kod onu ciziyor. Yani yeni konu
= yeni JSON, kod hic degismiyor.

Gemini'nin urettigi senaryolar bu seriyi kullaniyor ("series": "G").
Gemini kod yazmiyor, sadece katalogdan secim yapiyor -- gorsel dil boylece
10.000 videoda da ayni kaliyor.

Ardisik ve data'si olmayan beat'ler bir onceki sahneye katiliyor: ucuncu
satiri seslendirirken tablo ekranda kalsin diye.
"""
from .scenes import CATALOG


def _group(beats):
    """[(sahne_adi, data, [beat_id...])]"""
    groups = []
    for b in beats:
        # Sahne adi YAZILMAMIS beat bir onceki sahnede kalir. Eskiden
        # varsayilan "title"di: devam eden bir beat bos bir baslik sahnesi
        # aciyor ve orta ekran, tablo varken bile bos kaliyordu.
        name = b.get("scene") or (groups[-1][0] if groups else "title")
        if name not in CATALOG:
            raise ValueError(
                f"bilinmeyen sahne: {name!r} (beat {b['id']}). "
                f"Gecerli olanlar: {', '.join(CATALOG)}")
        data = b.get("data") or {}
        if groups and groups[-1][0] == name and not data:
            groups[-1][2].append(b["id"])
        else:
            groups.append((name, data, [b["id"]]))
    return groups


def stages(spec, S, duration):
    """[(t0, t1, fn)] -- build.render'in bekledigi bicim."""
    out = []
    groups = _group(spec["beats"])
    for i, (name, data, ids) in enumerate(groups):
        t0 = S[ids[0]][0]
        t1 = duration if i == len(groups) - 1 else S[ids[-1]][1] + 0.30

        def fn(d, t, S_, spec_, _f=CATALOG[name], _d=data, _a=t0, _b=t1, _n=name):
            dd = _d
            if _n == "close" and isinstance(_d.get("cta"), dict):
                # Konusulan CTA cumlesi varsa o baslayinca, yoksa (brand.json cta.spoken=false)
                # kapanis son cumlesi konusulurken chip'ler cikar.
                dd = {**_d, "cta_t0": S_["cta"][0] if "cta" in S_ else _a + SILENT_CTA_DELAY}
            _f(d, t, _a, _b, dd)

        out.append((t0, t1, fn))
    return out


SILENT_CTA_DELAY = 0.35    # sessiz CTA: kapanis sahnesi basladiktan sonra chip'ler cikar

STAGES = []          # build.py geriye donuk uyumluluk icin ariyor
