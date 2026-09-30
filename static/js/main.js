// スマホ用メニューの開閉
(function () {
  var btn = document.querySelector(".nav-toggle");
  var nav = document.getElementById("site-nav");
  if (!btn || !nav) return;
  btn.addEventListener("click", function () {
    var open = nav.classList.toggle("is-open");
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  });
  nav.addEventListener("click", function (e) {
    if (e.target.closest("a")) {
      nav.classList.remove("is-open");
      btn.setAttribute("aria-expanded", "false");
    }
  });
})();

// スマホの「無料相談」ボタンは少しスクロールしてから表示
(function () {
  var cta = document.querySelector(".float-cta");
  if (!cta) return;
  function update() { cta.classList.toggle("is-visible", window.scrollY > 500); }
  window.addEventListener("scroll", update, { passive: true });
  update();
})();
