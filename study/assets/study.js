// Shared behavior for every study page: topic rail, language toggle, source links, checklists.
(function () {
  const REPO = "https://github.com/TranXuanAnh930/i-dolly-backend";
  // Pinned commit so line numbers in links stay correct as the code moves on.
  const SHA = "4165dc059181f33a3877fab582dbd00af16311d4";

  const TOPICS = [
    { n: "01", file: "01-architecture.html", en: "Layered architecture & errors", ja: "レイヤードアーキテクチャとエラー処理", ready: true },
    { n: "02", file: "02-data-modeling.html", en: "Data modeling & schema design", ja: "データモデリングとスキーマ設計", ready: true },
    { n: "03", file: "03-migrations.html", en: "Migrations with Alembic", ja: "Alembic によるマイグレーション", ready: true },
    { n: "04", file: "04-authentication.html", en: "Authentication: JWT & refresh tokens", ja: "認証：JWT とリフレッシュトークン", ready: true },
    { n: "05", file: "05-authorization.html", en: "Authorization: RBAC & company scoping", ja: "認可：RBAC と会社スコープ", ready: true },
    { n: "06", file: "06-transactions-concurrency.html", en: "Transactions & concurrency", ja: "トランザクションと並行性", ready: true },
    { n: "07", file: "07-lottery-draw.html", en: "Lottery draw algorithm", ja: "抽選アルゴリズム", ready: true },
    { n: "08", file: "08-background-jobs.html", en: "Background jobs & side effects", ja: "バックグラウンドジョブと副作用", ready: true },
    { n: "09", file: "09-caching.html", en: "Caching with Redis", ja: "Redis によるキャッシュ", ready: false },
    { n: "10", file: "10-rate-limiting.html", en: "Rate limiting", ja: "レート制限", ready: false },
    { n: "11", file: "11-payments-idempotency.html", en: "Payments & idempotency", ja: "決済と冪等性", ready: false },
    { n: "12", file: "12-testing.html", en: "Testing strategy", ja: "テスト戦略", ready: false },
    { n: "13", file: "13-known-issues.html", en: "Known issues & tradeoffs", ja: "既知の問題とトレードオフ", ready: false },
    { n: "14", file: "14-scaling.html", en: "Scaling & system design", ja: "スケーリングとシステム設計", ready: false },
  ];

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } },
  };

  const here = location.pathname.split("/").pop() || "index.html";

  // ---- topic rail ----
  const rail = document.querySelector("[data-rail]");
  if (rail) {
    const ol = document.createElement("ol");
    for (const t of TOPICS) {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = t.file;
      if (!t.ready) a.className = "todo";
      if (t.file === here) a.setAttribute("aria-current", "page");
      a.innerHTML = `<span class="n">${t.n}</span><span><span lang="en">${t.en}</span><span lang="ja" class="sub">${t.ja}</span></span>`;
      li.appendChild(a);
      ol.appendChild(li);
    }
    // Collapsible on phones so the topic list doesn't push the page content down.
    const wrap = document.createElement("details");
    wrap.className = "rail-list";
    wrap.open = !matchMedia("(max-width: 860px)").matches;
    wrap.innerHTML = `<summary><span lang="en">Topics</span><span lang="ja">トピック</span></summary>`;
    wrap.appendChild(ol);
    rail.appendChild(wrap);
  }

  // ---- index cards ----
  const grid = document.querySelector("[data-cards]");
  if (grid) {
    for (const t of TOPICS) {
      const el = document.createElement(t.ready ? "a" : "div");
      el.className = "card" + (t.ready ? "" : " planned");
      if (t.ready) el.href = t.file;
      const done = Number(store.get(`study:${t.file}:done`) || 0);
      const total = Number(store.get(`study:${t.file}:total`) || 0);
      const prog = total ? `${done}/${total}` : "";
      el.innerHTML = `<span class="n">${t.n}</span>
        <span class="title"><span lang="en">${t.en}</span><span lang="ja" class="sub">${t.ja}</span></span>
        <span class="meta"><span class="pill ${t.ready ? "ready" : "planned"}">${t.ready ? "ready" : "planned"}</span>
        <span class="progress">${prog}</span></span>`;
      grid.appendChild(el);
    }
  }

  // ---- prev / next ----
  const pager = document.querySelector("[data-pager]");
  if (pager) {
    const i = TOPICS.findIndex((t) => t.file === here);
    const prev = TOPICS[i - 1], next = TOPICS[i + 1];
    pager.innerHTML =
      (prev ? `<a href="${prev.file}">← ${prev.n} <span lang="en">${prev.en}</span><span lang="ja">${prev.ja}</span></a>` : `<a href="index.html">← Index</a>`) +
      (next ? `<a href="${next.file}">${next.n} <span lang="en">${next.en}</span><span lang="ja">${next.ja}</span> →</a>` : `<a href="index.html">Index →</a>`);
  }

  // ---- language toggle: en / ja / both ----
  const root = document.documentElement;
  function setLang(l) {
    root.dataset.lang = l;
    store.set("study:lang", l);
    document.querySelectorAll(".langs button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.l === l)));
  }
  document.querySelectorAll(".langs button").forEach((b) => b.addEventListener("click", () => setLang(b.dataset.l)));
  setLang(store.get("study:lang") || "en");

  // ---- source links: <a class="ref" data-p="path" data-l="12"> ----
  document.querySelectorAll("a.ref[data-p]").forEach((a) => {
    const p = a.dataset.p, l = a.dataset.l;
    a.href = `${REPO}/blob/${SHA}/${p}${l ? `#L${l.replace("-", "-L")}` : ""}`;
    a.target = "_blank";
    a.rel = "noopener";
    if (!a.textContent.trim()) a.textContent = l ? `${p}:${l}` : p;
  });

  // ---- checklist with saved progress ----
  const boxes = [...document.querySelectorAll(".checklist input[type=checkbox]")];
  const out = document.querySelector("[data-progress]");
  function tally() {
    const done = boxes.filter((b) => b.checked).length;
    if (out) out.textContent = `${done} / ${boxes.length}`;
    store.set(`study:${here}:done`, String(done));
    store.set(`study:${here}:total`, String(boxes.length));
  }
  boxes.forEach((b, i) => {
    b.id = b.id || `chk-${i}`;
    const key = `study:${here}:${b.id}`;
    b.checked = store.get(key) === "1";
    b.addEventListener("change", () => { store.set(key, b.checked ? "1" : "0"); tally(); });
  });
  if (boxes.length) tally();

  // ---- expand / collapse all answers ----
  document.querySelectorAll("[data-toggle-answers]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const open = btn.dataset.toggleAnswers === "open";
      document.querySelectorAll("details.q").forEach((d) => (d.open = open));
    });
  });
})();
