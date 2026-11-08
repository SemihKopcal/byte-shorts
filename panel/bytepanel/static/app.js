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
