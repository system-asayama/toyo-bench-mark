// ブログ編集画面：ツールバー・画像挿入・プレビュー・未保存の警告
(function () {
  var form = document.getElementById("post-form");
  var body = document.getElementById("body");
  if (!form || !body) return;
  var csrf = form.querySelector("input[name=csrf]").value;
  var box = body.closest(".editor__box");
  var preview = document.getElementById("preview");
  var dirty = false;

  form.addEventListener("input", function () { dirty = true; });
  form.addEventListener("submit", function () { dirty = false; });
  window.addEventListener("beforeunload", function (e) {
    if (dirty) { e.preventDefault(); e.returnValue = ""; }
  });

  function insert(before, after, placeholder) {
    var s = body.selectionStart, e = body.selectionEnd;
    var sel = body.value.slice(s, e) || placeholder || "";
    body.setRangeText(before + sel + (after || ""), s, e, "end");
    if (!body.value.slice(s, e).length && placeholder) {
      body.setSelectionRange(s + before.length, s + before.length + sel.length);
    }
    body.focus();
    dirty = true;
  }

  function linePrefix(prefix, placeholder) {
    var s = body.selectionStart;
    var lineStart = body.value.lastIndexOf("\n", s - 1) + 1;
    var needNl = lineStart !== s ? "\n" : "";
    insert(needNl + prefix, "", placeholder);
  }

  var actions = {
    h2: function () { linePrefix("## ", "見出し"); },
    h3: function () { linePrefix("### ", "小見出し"); },
    bold: function () { insert("**", "**", "太字にする文字"); },
    ul: function () { linePrefix("- ", "項目"); },
    ol: function () { linePrefix("1. ", "項目"); },
    quote: function () { linePrefix("> ", "引用文"); },
    link: function () {
      var url = prompt("リンク先の URL を入力してください", "https://");
      if (url) insert("[", "](" + url + ")", "リンクの文字");
    }
  };
  document.querySelectorAll("[data-md]").forEach(function (b) {
    b.addEventListener("click", function () { actions[b.dataset.md](); });
  });

  // 画像アップロードして本文に挿入
  var fileInput = document.getElementById("body-image");
  fileInput.addEventListener("change", function () {
    var f = fileInput.files[0];
    if (!f) return;
    var fd = new FormData();
    fd.append("csrf", csrf);
    fd.append("file", f);
    box.classList.add("is-uploading");
    fetch("/admin/images", { method: "POST", body: fd, credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error(res.j.detail || "アップロードに失敗しました");
        linePrefix("![](" + res.j.url + ")\n", "");
      })
      .catch(function (err) { alert(err.message); })
      .finally(function () { box.classList.remove("is-uploading"); fileInput.value = ""; });
  });

  // 書く / プレビュー 切り替え
  var toolbar = document.querySelector(".editor__toolbar");
  document.querySelectorAll(".editor__tabs button").forEach(function (tab) {
    tab.addEventListener("click", function () {
      document.querySelectorAll(".editor__tabs button").forEach(function (t) { t.classList.toggle("is-active", t === tab); });
      var isPreview = tab.dataset.tab === "preview";
      body.hidden = isPreview; toolbar.hidden = isPreview; preview.hidden = !isPreview;
      if (isPreview) {
        preview.innerHTML = "<p class='muted'>読み込み中…</p>";
        var fd = new FormData();
        fd.append("csrf", csrf);
        fd.append("body", body.value);
        fetch("/admin/preview", { method: "POST", body: fd, credentials: "same-origin" })
          .then(function (r) { return r.text(); })
          .then(function (html) { preview.innerHTML = html || "<p class='muted'>本文がありません</p>"; });
      }
    });
  });
})();
