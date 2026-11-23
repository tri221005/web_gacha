/* Admin console. Plain fetch + DOM, no framework: the console only needs
   tables, forms and a toast. */
(function () {
  "use strict";

  const CSRF = (document.querySelector('meta[name="csrf"]') || {}).content || "";
  const PAGE = window.location.pathname;

  function toast(message, isError) {
    const box = document.getElementById("admin-toast");
    if (!box) return;
    box.textContent = message;
    box.classList.toggle("err", !!isError);
    box.classList.add("show");
    clearTimeout(box._timer);
    box._timer = setTimeout(function () { box.classList.remove("show"); }, 3600);
  }

  async function api(path, options) {
    const opts = Object.assign({ headers: {} }, options || {});
    opts.headers = Object.assign({ "X-CSRF": CSRF }, opts.headers);
    if (opts.body && typeof opts.body !== "string") {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    const response = await fetch(path, opts);
    let data = {};
    try { data = await response.json(); } catch (e) { data = {}; }
    if (!response.ok) {
      throw new Error(data.detail || "Lỗi " + response.status);
    }
    return data;
  }

  function esc(value) {
    const div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  }

  // ---- Tabs -------------------------------------------------------------
  const tabs = Array.from(document.querySelectorAll(".admin-tab"));
  const panels = Array.from(document.querySelectorAll(".admin-panel"));
  function showTab(name) {
    tabs.forEach(function (tab) {
      tab.classList.toggle("on", tab.dataset.tab === name);
    });
    panels.forEach(function (panel) {
      panel.classList.toggle("hidden", panel.dataset.panel !== name);
    });
    if (history.replaceState) {
      history.replaceState(null, "", "/admin?tab=" + name);
    }
    loadTab(name);
  }
  tabs.forEach(function (tab) {
    tab.addEventListener("click", function (event) {
      event.preventDefault();
      showTab(tab.dataset.tab);
    });
  });
  const activeTab = tabs.find(function (t) { return t.classList.contains("on"); });
  const currentTab = activeTab ? activeTab.dataset.tab : "overview";

  // ---- Trạng thái server ------------------------------------------------
  async function loadServer() {
    const box = document.getElementById("server-status");
    if (!box) return;
    try {
      const info = await api("/api/admin/server");
      const ok = info.console && !info.error;
      box.classList.toggle("ok", ok);
      box.classList.toggle("bad", !ok);
      const name = info.server ? info.server.name || info.server.short : "không rõ";
      box.querySelector(".txt").textContent = ok
        ? "Server " + name + (info.dry_run ? " · dry-run" : " · live")
        : (info.error || "Không kết nối được server");
    } catch (err) {
      box.classList.add("bad");
      box.querySelector(".txt").textContent = err.message;
    }
  }

  // ---- Người chơi -------------------------------------------------------
  let playerTimer = null;
  async function loadPlayers() {
    const body = document.getElementById("players-body");
    if (!body) return;
    const search = (document.getElementById("players-search") || {}).value || "";
    const bots = (document.getElementById("players-bots") || {}).checked ? 1 : 0;
    try {
      const data = await api("/api/admin/players?search=" + encodeURIComponent(search) + "&bots=" + bots);
      const rows = data.players || [];
      body.innerHTML = rows.map(function (row) {
        const flags = (row.is_bot ? " <span class=\"admin-flag\">bot</span>" : "")
          + (row.banned ? " <span class=\"admin-flag warn\">bị cấm</span>" : "");
        return "<tr>"
          + "<td><a href=\"/admin/player/" + encodeURIComponent(row.player) + "\">"
          + esc(row.player) + "</a>" + flags + "</td>"
          + "<td>" + esc(row.balance_fmt) + "</td>"
          + "<td>" + row.pulls + "</td>"
          + "<td>" + esc(row.spent_fmt) + "</td>"
          + "<td>" + row.held + "</td>"
          + "<td class=\"admin-row-actions\">"
          + "<button class=\"ghost\" type=\"button\" data-player=\""
          + esc(row.player) + "\">Quản lý</button></td></tr>";
      }).join("");
      const empty = document.getElementById("players-empty");
      if (empty) empty.hidden = rows.length > 0;
      const count = document.getElementById("players-count");
      if (count) count.textContent = rows.length + " người chơi";
    } catch (err) {
      toast(err.message, true);
    }
  }

  const playersSearch = document.getElementById("players-search");
  if (playersSearch) {
    playersSearch.addEventListener("input", function () {
      clearTimeout(playerTimer);
      playerTimer = setTimeout(loadPlayers, 250);
    });
  }
  const playersBots = document.getElementById("players-bots");
  if (playersBots) playersBots.addEventListener("change", loadPlayers);

  document.addEventListener("click", function (event) {
    const button = event.target.closest("[data-player]");
    if (!button) return;
    window.location.href = "/admin/player/" + encodeURIComponent(button.dataset.player);
  });

  // ---- Giao dịch --------------------------------------------------------
  let txTimer = null;
  async function loadTx() {
    const body = document.getElementById("tx-body");
    if (!body) return;
    const search = (document.getElementById("tx-search") || {}).value || "";
    const kind = (document.getElementById("tx-kind") || {}).value || "";
    try {
      const data = await api("/api/admin/tx?search=" + encodeURIComponent(search) + "&kind=" + encodeURIComponent(kind));
      const rows = data.tx || [];
      body.innerHTML = rows.map(function (row) {
        const negative = row.amount < 0;
        return "<tr>"
          + "<td>" + esc(row.when) + "</td>"
          + "<td><a href=\"/admin/player/" + encodeURIComponent(row.player) + "\">"
          + esc(row.player) + "</a></td>"
          + "<td>" + esc(row.kind_label) + "</td>"
          + "<td class=\"" + (negative ? "neg" : "pos") + "\">"
          + esc(row.amount_fmt) + "</td>"
          + "<td>" + esc(row.note) + "</td></tr>";
      }).join("");
      const empty = document.getElementById("tx-empty");
      if (empty) empty.hidden = rows.length > 0;
      const count = document.getElementById("tx-count");
      if (count) count.textContent = rows.length + " giao dịch";
    } catch (err) {
      toast(err.message, true);
    }
  }
  const txSearch = document.getElementById("tx-search");
  if (txSearch) {
    txSearch.addEventListener("input", function () {
      clearTimeout(txTimer);
      txTimer = setTimeout(loadTx, 250);
    });
  }
  const txKind = document.getElementById("tx-kind");
  if (txKind) txKind.addEventListener("change", loadTx);

  // ---- Rương ------------------------------------------------------------
  const RARITIES = ["consumer", "industrial", "milspec", "restricted",
                     "classified", "covert", "extraordinary"];

  function caseCard(item) {
    const rows = (item.items || []).map(function (entry) {
      return "<tr data-item-id=\"" + esc(entry.id) + "\">"
        + "<td>" + esc(entry.name) + "</td>"
        + "<td><select data-field=\"rarity\">" + RARITIES.map(function (r) {
            return "<option" + (r === entry.rarity ? " selected" : "") + ">" + r + "</option>";
          }).join("") + "</select></td>"
        + "<td><input type=\"number\" step=\"0.001\" min=\"0\" value=\"" + entry.weight + "\" data-field=\"weight\"></td>"
        + "<td>" + entry.percent + "%</td>"
        + "<td><input type=\"number\" step=\"1\" min=\"0\" value=\"" + entry.coin + "\" data-field=\"coin\"></td>"
        + "<td><button class=\"ghost\" type=\"button\" data-remove-item=\"" + esc(entry.id) + "\">Xoá</button></td>"
        + "</tr>";
    }).join("");
    return "<div class=\"case-admin-card\" data-case-id=\"" + esc(item.id) + "\">"
      + "<div class=\"case-admin-head\">"
      + "<input class=\"case-id\" value=\"" + esc(item.id) + "\" aria-label=\"ID rương\">"
      + "<input class=\"case-name\" value=\"" + esc(item.name) + "\" aria-label=\"Tên rương\">"
      + "<label class=\"case-cost\">Giá <input type=\"number\" class=\"case-pull-cost\" min=\"1\" value=\"" + item.pull_cost + "\"></label>"
      + "<span class=\"case-rtp" + (item.rtp > 100 ? " case-rtp-over" : "") + "\">RTP lý thuyết " + item.rtp + "%"
      + (item.rtp > 100 ? " (lỗ)" : "") + "</span>"
      + "<button class=\"ghost\" type=\"button\" data-save-case=\"" + esc(item.id) + "\">Lưu</button>"
      + "<button class=\"ghost danger\" type=\"button\" data-delete-case=\"" + esc(item.id) + "\">Xoá rương</button>"
      + "</div>"
      + "<textarea class=\"case-desc\" rows=\"2\" aria-label=\"Mô tả\">" + esc(item.description) + "</textarea>"
      + "<div class=\"table-scroll\"><table class=\"case-items\">"
      + "<thead><tr><th>Tên</th><th>Độ hiếm</th><th>Trọng số</th><th>Tỉ lệ</th><th>Giá trị</th><th></th></tr></thead>"
      + "<tbody>" + rows + "</tbody></table></div>"
      + "<div class=\"admin-form-row\">"
      + "<input class=\"new-item-name\" placeholder=\"Tên món mới\" aria-label=\"Tên món mới\">"
      + "<input class=\"new-item-id\" placeholder=\"ID món\" aria-label=\"ID món mới\">"
      + "<input type=\"number\" class=\"new-item-coin\" placeholder=\"Giá trị\" min=\"0\" aria-label=\"Giá trị món mới\">"
      + "<input type=\"number\" class=\"new-item-weight\" placeholder=\"Trọng số\" min=\"0\" step=\"0.001\" value=\"1\" aria-label=\"Trọng số món mới\">"
      + "<select class=\"new-item-rarity\" aria-label=\"Độ hiếm món mới\">" + RARITIES.map(function (r) {
          return "<option" + (r === "consumer" ? " selected" : "") + ">" + r + "</option>";
        }).join("") + "</select>"
      + "<button class=\"ghost\" type=\"button\" data-add-item=\"" + esc(item.id) + "\">Thêm món</button>"
      + "</div>"
      + "</div>";
  }

  async function loadCases() {
    const list = document.getElementById("cases-list");
    if (!list) return;
    try {
      const data = await api("/api/admin/cases");
      const cases = data.cases || [];
      list.innerHTML = cases.map(caseCard).join("");
    } catch (err) {
      toast(err.message, true);
    }
  }

  function collectCase(card) {
    const caseId = card.querySelector(".case-id").value.trim();
    const name = card.querySelector(".case-name").value.trim();
    const description = card.querySelector(".case-desc").value;
    const pullCost = parseInt(card.querySelector(".case-pull-cost").value, 10) || 0;
    const items = Array.from(card.querySelectorAll(".case-items tbody tr"))
      .map(function (row) {
        const cells = row.children;
        return {
          id: row.dataset.itemId || "",
          name: cells[0].textContent.trim(),
          rarity: cells[1].querySelector("select").value,
          weight: parseFloat(cells[2].querySelector("input").value) || 0,
          coin: parseInt(cells[4].querySelector("input").value, 10) || 0,
        };
      })
      .filter(function (item) { return item.id; });
    return { id: caseId, name: name, description: description,
             pull_cost: pullCost, items: items };
  }

  document.addEventListener("click", async function (event) {
    const save = event.target.closest("[data-save-case]");
    const del = event.target.closest("[data-delete-case]");
    const add = event.target.closest("[data-add-item]");
    const remove = event.target.closest("[data-remove-item]");

    if (save) {
      const card = save.closest(".case-admin-card");
      try {
        const data = await api("/api/admin/cases", { method: "POST", body: { case: collectCase(card) } });
        toast(data.message || "Đã lưu.");
        loadCases();
      } catch (err) {
        toast(err.message, true);
      }
      return;
    }

    if (del) {
      if (!confirm("Xoá rương " + del.dataset.deleteCase + "?")) return;
      try {
        const data = await api("/api/admin/cases/" + encodeURIComponent(del.dataset.deleteCase), { method: "DELETE" });
        toast(data.message || "Đã xoá.");
        loadCases();
      } catch (err) {
        toast(err.message, true);
      }
      return;
    }

    if (add) {
      const card = add.closest(".case-admin-card");
      const name = card.querySelector(".new-item-name").value.trim();
      const id = card.querySelector(".new-item-id").value.trim();
      const coin = parseInt(card.querySelector(".new-item-coin").value, 10) || 0;
      const weight = parseFloat(card.querySelector(".new-item-weight").value) || 0;
      const rarity = card.querySelector(".new-item-rarity").value;
      if (!name || !id) { toast("Cần tên và ID món.", true); return; }
      const payload = collectCase(card);
      payload.items.push({ id: id, name: name, rarity: rarity, weight: weight, coin: coin });
      try {
        const data = await api("/api/admin/cases", { method: "POST", body: { case: payload } });
        toast(data.message || "Đã lưu.");
        loadCases();
      } catch (err) {
        toast(err.message, true);
      }
      return;    }

    if (remove) {
      const card = remove.closest(".case-admin-card");
      const payload = collectCase(card);
      payload.items = payload.items.filter(function (item) {
        return item.id !== remove.dataset.removeItem;
      });
      try {
        const data = await api("/api/admin/cases", { method: "POST", body: { case: payload } });
        toast(data.message || "Đã lưu.");
        loadCases();
      } catch (err) {
        toast(err.message, true);
      }
    }
  });

  const caseNew = document.getElementById("case-new");
  if (caseNew) {
    caseNew.addEventListener("click", function () {
      const list = document.getElementById("cases-list");
      const draft = {
        id: "new-case", name: "Rương mới", description: "", pull_cost: 5000,
        rtp: 0, items: [],
      };
      list.insertAdjacentHTML("afterbegin", caseCard(draft));
      list.firstElementChild.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  // ---- Battle -----------------------------------------------------------
  async function loadBattles() {
    const list = document.getElementById("battles-list");
    if (!list) return;
    try {
      const data = await api("/api/admin/battles");
      const battles = data.battles || [];
      list.innerHTML = battles.map(function (battle) {
        const seats = (battle.players || []).map(function (seat) {
          return "<span class=\"seat-pill" + (seat.is_bot ? " bot" : "") + "\">"
            + esc(seat.player) + " · " + esc(seat.total_fmt) + "</span>";
        }).join("");
        const running = battle.status === "WAITING";
        return "<div class=\"battle-admin-card\">"
          + "<div class=\"battle-card-top\"><span>#" + battle.id + "</span>"
          + "<span>" + esc(battle.case_id) + "</span>"
          + "<span>" + battle.rounds + " vòng</span>"
          + "<span>" + esc(battle.mode) + "</span>"
          + "<span class=\"mode-pill\">" + esc(battle.status) + "</span>"
          + "<span>" + esc(battle.created_fmt) + "</span></div>"
          + "<div class=\"seat-pills\">" + seats + "</div>"
          + (battle.winner ? "<p class=\"meta\">Thắng: " + esc(battle.winner) + "</p>" : "")
          + (running
            ? "<div class=\"admin-form-row\">"
              + "<button class=\"ghost\" type=\"button\" data-battle-finish=\"" + battle.id + "\">Kết thúc trận</button>"
              + "<button class=\"ghost danger\" type=\"button\" data-battle-cancel=\"" + battle.id + "\">Huỷ &amp; hoàn Coin</button>"
              + "</div>"
            : "")
          + "</div>";
      }).join("") || "<p class=\"hint\">Chưa có trận nào.</p>";
      const count = document.getElementById("battles-count");
      if (count) count.textContent = battles.length + " trận";
    } catch (err) {
      toast(err.message, true);
    }
  }

  document.addEventListener("click", async function (event) {
    const finish = event.target.closest("[data-battle-finish]");
    const cancel = event.target.closest("[data-battle-cancel]");
    if (finish) {
      try {
        const data = await api("/api/admin/battles/" + finish.dataset.battleFinish + "/finish", { method: "POST" });
        toast(data.message || "Đã kết thúc trận.");
        loadBattles();
      } catch (err) {
        toast(err.message, true);
      }
      return;
    }
    if (cancel) {
      if (!confirm("Huỷ trận #" + cancel.dataset.battleCancel + " và hoàn Coin cho mọi người?")) return;
      try {
        const data = await api("/api/admin/battles/" + cancel.dataset.battleCancel + "/cancel", { method: "POST" });
        toast(data.message || "Đã huỷ trận.");
        loadBattles();
      } catch (err) {
        toast(err.message, true);
      }
    }
  });

  const battlesRefresh = document.getElementById("battles-refresh");
  if (battlesRefresh) battlesRefresh.addEventListener("click", loadBattles);

  // ---- Nhật ký admin ----------------------------------------------------
  async function loadLog() {
    const body = document.getElementById("log-body");
    if (!body) return;
    try {
      const data = await api("/api/admin/log");
      const rows = data.log || [];
      body.innerHTML = rows.map(function (row) {
        return "<tr>"
          + "<td>" + esc(row.when) + "</td>"
          + "<td>" + esc(row.admin) + "</td>"
          + "<td>" + esc(row.action) + "</td>"
          + "<td>" + esc(row.target) + "</td>"
          + "<td>" + esc(row.detail) + "</td></tr>";
      }).join("");
      const empty = document.getElementById("log-empty");
      if (empty) empty.hidden = rows.length > 0;
      const count = document.getElementById("log-count");
      if (count) count.textContent = rows.length + " thao tac";
    } catch (err) {
      toast(err.message, true);
    }
  }
  const logRefresh = document.getElementById("log-refresh");
  if (logRefresh) logRefresh.addEventListener("click", loadLog);

  // ---- Đội ngũ admin ----------------------------------------------------
  async function loadAdmins(refresh) {
    const body = document.getElementById("admins-body");
    if (!body) return;
    const meta = document.getElementById("admins-meta");
    const errorBox = document.getElementById("admins-error");
    try {
      const data = await api("/api/admin/admins" + (refresh ? "?refresh=1" : ""));
      const rows = data.admins || [];
      body.innerHTML = rows.map(function (row) {
        return "<tr>"
          + "<td>" + esc(row.name) + "</td>"
          + "<td>" + (row.web ? '<span class="admin-flag ok">có</span>'
                                : '<span class="admin-flag">không</span>') + "</td>"
          + "<td>" + (row.server ? '<span class="admin-flag ok">có</span>'
                                  : '<span class="admin-flag">không</span>') + "</td>"
          + "<td>" + esc(row.source || "—") + "</td>"
          + "<td class=\"admin-row-actions\">"
          + (row.server
            ? "<button class=\"ghost danger\" type=\"button\" data-admin-revoke=\""
              + esc(row.name) + "\">Gỡ quyền</button>"
            : "<button class=\"ghost\" type=\"button\" data-admin-grant=\""
              + esc(row.name) + "\">Cấp quyền</button>")
          + "</td></tr>";
      }).join("") || '<tr><td colspan="5">Chưa có admin nào.</td></tr>';
      if (errorBox) {
        errorBox.hidden = !data.server_error;
        errorBox.textContent = data.server_error || "";
      }
      if (meta) {
        meta.textContent = rows.length + " admin · group " + (data.server_group || "admin")
          + (data.synced_at ? " · đồng bộ " + data.synced_at : "");
      }
    } catch (err) {
      if (errorBox) { errorBox.hidden = false; errorBox.textContent = err.message; }
      toast(err.message, true);
    }
  }

  document.addEventListener("click", async function (event) {
    const grant = event.target.closest("[data-admin-grant]");
    const revoke = event.target.closest("[data-admin-revoke]");
    if (grant) {
      const name = grant.dataset.adminGrant;
      try {
        const data = await api("/api/admin/admins", { method: "POST", body: { name: name, action: "grant" } });
        toast(data.message || "Đã cấp quyền.");
        loadAdmins(true);
      } catch (err) { toast(err.message, true); }
      return;
    }
    if (revoke) {
      const name = revoke.dataset.adminRevoke;
      if (!confirm("Gỡ quyền admin của " + name + " trên server?")) return;
      try {
        const data = await api("/api/admin/admins", { method: "POST", body: { name: name, action: "revoke" } });
        toast(data.message || "Đã gỡ quyền.");
        loadAdmins(true);
      } catch (err) { toast(err.message, true); }
    }
  });

  const adminsRefresh = document.getElementById("admins-refresh");
  if (adminsRefresh) {
    adminsRefresh.addEventListener("click", function () {
      loadAdmins(true).then(function () { toast("Đã tải danh sách từ server."); });
    });
  }

  const adminGrant = document.getElementById("admin-grant");
  if (adminGrant) {
    adminGrant.addEventListener("click", async function () {
      const input = document.getElementById("admin-new-name");
      const name = (input.value || "").trim();
      if (!name) { toast("Nhập tên tài khoản.", true); return; }
      try {
        const data = await api("/api/admin/admins", { method: "POST", body: { name: name, action: "grant" } });
        toast(data.message || "Đã cấp quyền.");
        input.value = "";
        loadAdmins(true);
      } catch (err) { toast(err.message, true); }
    });
  }

  // ---- Hồ sơ người chơi -------------------------------------------------
  if (PAGE.startsWith("/admin/player/")) {
    const player = decodeURIComponent(PAGE.replace("/admin/player/", ""));
    document.querySelectorAll("[data-coin]").forEach(function (button) {
      button.addEventListener("click", async function () {
        const amount = parseInt((document.getElementById("coin-amount") || {}).value, 10) || 0;
        if (amount <= 0) { toast("Nhập số Coin cần thay đổi.", true); return; }
        try {
          const data = await api("/api/admin/players/" + encodeURIComponent(player) + "/coin",
            { method: "POST", body: { amount: amount, direction: button.dataset.coin } });
          toast(data.message || "Đã cập nhật ví.");
          setTimeout(function () { window.location.reload(); }, 900);
        } catch (err) {
          toast(err.message, true);
        }
      });
    });

    const coinSet = document.getElementById("coin-set");
    if (coinSet) {
      coinSet.addEventListener("click", async function () {
        const amount = parseInt((document.getElementById("coin-balance") || {}).value, 10);
        if (amount === null || isNaN(amount) || amount < 0) {
          toast("Nhập số dư hợp lệ.", true);
          return;
        }
        try {
          const data = await api("/api/admin/players/" + encodeURIComponent(player) + "/balance",
            { method: "POST", body: { balance: amount } });
          toast(data.message || "Đã đặt ví.");
          setTimeout(function () { window.location.reload(); }, 900);
        } catch (err) {
          toast(err.message, true);
        }
      });
    }

    const banSet = document.getElementById("ban-set");
    if (banSet) {
      banSet.addEventListener("click", async function () {
        const reason = (document.getElementById("ban-reason") || {}).value || "";
        if (!confirm("Cấm " + player + "?")) return;
        try {
          const data = await api("/api/admin/players/" + encodeURIComponent(player) + "/ban",
            { method: "POST", body: { banned: true, reason: reason } });
          toast(data.message || "Đã cấm.");
          setTimeout(function () { window.location.reload(); }, 900);
        } catch (err) {
          toast(err.message, true);
        }
      });
    }

    const banLift = document.getElementById("ban-lift");
    if (banLift) {
      banLift.addEventListener("click", async function () {
        try {
          const data = await api("/api/admin/players/" + encodeURIComponent(player) + "/ban",
            { method: "POST", body: { banned: false } });
          toast(data.message || "Đã gỡ cấm.");
          setTimeout(function () { window.location.reload(); }, 900);
        } catch (err) {
          toast(err.message, true);
        }
      });
    }
  }

  // ---- Nút làm mới chung -------------------------------------------------
  const refresh = document.getElementById("admin-refresh");
  if (refresh) {
    refresh.addEventListener("click", function () {
      loadServer();
      loadTab(currentTab);
      toast("Đã làm mới.");
    });
  }

  function loadTab(name) {
    if (name === "players") loadPlayers();
    else if (name === "cases") loadCases();
    else if (name === "tx") loadTx();
    else if (name === "battles") loadBattles();
    else if (name === "admins") loadAdmins(false);
    else if (name === "log") loadLog();
  }

  loadServer();
  loadTab(currentTab);

  /* ---- Tự làm mới ------------------------------------------------------
   * The console is watched while it is open, so the numbers stay right
   * without pressing the button. The tab that is open is the only one
   * that is refreshed, and the poll backs off while nothing changes.
   */
  const AUTO_DELAY = 6000;
  let autoTimer = null;

  function scheduleAuto() {
    if (autoTimer) clearTimeout(autoTimer);
    autoTimer = setTimeout(function () {
      if (document.hidden) {
        scheduleAuto();
        return;
      }
      loadServer();
      loadTab(currentTab);
      scheduleAuto();
    }, AUTO_DELAY);
  }

  // The player and battle lists change on their own, so they are polled
  // often. The case list only changes when the admin edits it, so it is
  // left alone to not fight with the form while it is being filled in.
  // The overview is rendered on the server, so it has no loader here.
  const AUTO_TABS = ["players", "tx", "battles", "log"];
  if (AUTO_TABS.indexOf(currentTab) !== -1) scheduleAuto();
})();
