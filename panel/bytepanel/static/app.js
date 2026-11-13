document.addEventListener('submit', function (e) {
  var m = e.target && e.target.dataset ? e.target.dataset.confirm : '';
  if (m && !window.confirm(m)) e.preventDefault();
});
document.querySelectorAll('[data-preview]').forEach(function (btn) {
  btn.addEventListener('click', function () {
    fetch(btn.dataset.preview, {credentials: 'same-origin', headers: {Accept: 'application/json'}})
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var v = document.getElementById('player');
        if (j.url) { v.src = j.url; v.hidden = false; btn.hidden = true; }
        else { btn.textContent = j.error || 'Onizleme yok'; btn.disabled = true; }
      })
      .catch(function () { btn.textContent = 'Onizleme acilamadi'; });
  });
});

// Takvim: planli yayini baska gune surukle-birak. Yalniz formu doldurup gonderir; asil kurallar
// (gecmis gun, cakisma, yalniz 'planli') sunucuda. Dokunmatikte surukleme yoksa gun sayfasindaki
// "Tasi" kutusu ayni isi yapar.
(function () {
  var form = document.getElementById('move-form');
  if (!form) return;
  var dragged = null;
  function clear() {
    document.querySelectorAll('.cell.over').forEach(function (c) { c.classList.remove('over'); });
  }
  document.querySelectorAll('.chip[data-pub]').forEach(function (chip) {
    chip.addEventListener('dragstart', function (e) {
      dragged = chip.dataset.pub;
      chip.classList.add('dragging');
      if (e.dataTransfer) { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', dragged); }
    });
    chip.addEventListener('dragend', function () { chip.classList.remove('dragging'); clear(); dragged = null; });
  });
  document.querySelectorAll('.cell[data-drop]').forEach(function (cell) {
    cell.addEventListener('dragover', function (e) {
      if (!dragged) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
      cell.classList.add('over');
    });
    cell.addEventListener('dragleave', function () { cell.classList.remove('over'); });
    cell.addEventListener('drop', function (e) {
      if (!dragged) return;
      e.preventDefault();
      form.elements.pub.value = dragged;
      form.elements.d.value = cell.dataset.day;
      form.submit();
    });
  });
})();

// Hikaye formu: okunacak cumlelerdeki kelimelerden tahmini sureyi canli hesaplar (kurallar
// editorial/rules.py ile ayni: dakikada 2.6 kelime + cumle arasi 0.18 sn, en fazla 52 sn). Yalniz bilgi
// icindir; kesin karar sunucuda ve depodaki kapida.
(function () {
  var box = document.getElementById('est');
  if (!box) return;
  var form = box.closest('form');
  function calc() {
    var words = 0, beats = 0;
    form.querySelectorAll('input[name^="say_"]').forEach(function (el) {
      var t = el.value.trim();
      if (!t) return;
      beats += 1;
      words += t.split(/\s+/).length;
    });
    var secs = Math.round(words / 2.6 + 0.18 * Math.max(beats - 1, 0));
    box.querySelector('[data-beats]').textContent = beats;
    box.querySelector('[data-words]').textContent = words;
    box.querySelector('[data-secs]').textContent = secs;
    box.classList.toggle('over', secs > 52 || beats > 14 || (beats > 0 && beats < 10));
  }
  form.addEventListener('input', calc);
  calc();
})();
