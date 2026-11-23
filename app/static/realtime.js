/* Live updates for the whole site.
 *
 * The pages are server rendered, so anything that changes on the server
 * would only show up after a reload. This module polls the JSON APIs and
 * patches the page in place.
 *
 * The polling stops while the tab is hidden and picks up again when the
 * tab comes back, so a background tab does not keep hitting the server.
 */
(function () {
  "use strict";

  // How long to wait before the next poll, in milliseconds. The value
  // grows while the answers do not change, and drops back to the base
  // delay as soon as something does change.
  const BASE_DELAY = 5000;
  const MAX_DELAY = 60000;

  function pause() {
    return document.hidden;
  }

  /* A poller that keeps asking one URL and hands every answer to a
   * callback. The delay grows while the answer stays the same, so a
   * quiet page costs very little.
   */
  function poll(url, onData, options) {
    const opts = options || {};
    const base = opts.delay || BASE_DELAY;
    let delay = base;
    let timer = null;
    let stopped = false;
    let last = null;

    async function tick() {
      if (stopped) return;
      if (pause()) {
        // Wait for the tab to come back rather than spinning in the
        // background.
        timer = setTimeout(tick, 2000);
        return;
      }
      try {
        const res = await fetch(url, {
          headers: { accept: "application/json" },
          cache: "no-store",
        });
        if (res.ok) {
          const data = await res.json();
          const changed = last === null || JSON.stringify(data) !== last;
          last = JSON.stringify(data);
          if (changed) {
            delay = base;
            try {
              onData(data);
            } catch (err) {
              /* a broken patch must not stop the poller */
            }
          } else {
            delay = Math.min(MAX_DELAY, Math.round(delay * 1.5));
          }
        } else {
          delay = Math.min(MAX_DELAY, delay * 2);
        }
      } catch (err) {
        // The server is unreachable. Back off, but keep trying.
        delay = Math.min(MAX_DELAY, delay * 2);
      }
      timer = setTimeout(tick, delay);
    }

    function stop() {
      stopped = true;
      if (timer) clearTimeout(timer);
    }

    document.addEventListener("visibilitychange", function () {
      if (!document.hidden && timer) {
        clearTimeout(timer);
        timer = setTimeout(tick, 200);
      }
    });

    tick();
    return { stop: stop, refresh: function () { delay = base; } };
  }

  /* ---- The Coin balance in the header ------------------------------- */
  /* The header shows the balance on every page. The number can change on
   * the Minecraft server without the player doing anything here, so it
   * is polled and patched in place.
   *
   * The cheap endpoint is used, not the live one: this runs on every
   * page, so it must not talk to the Minecraft server each time.
   */
  function liveBalance() {
    const chip = document.querySelector(".coin-chip span");
    if (!chip) return;
    poll("/api/wallet/balance", function (data) {
      if (typeof data.balance_fmt !== "string") return;
      if (chip.textContent.trim() !== (data.balance_fmt + " Coin").trim()) {
        chip.textContent = data.balance_fmt + " Coin";
      }
    }, { delay: 8000 });
  }

  /* ---- The number of items in the bag ------------------------------- */
  /* The header shows how many items the player is holding. Selling an
   * item changes it, so it is polled too.
   */
  function liveBagCount() {
    const link = document.querySelector('a.nav-link[href="/inventory"]');
    if (!link) return;
    poll("/api/wallet/balance", function (data) {
      if (typeof data.held !== "number") return;
      const wanted = data.held > 0 ? " " + data.held : "";
      if (link.textContent.replace(/\s+/g, " ").trim() !== ("Túi đồ" + wanted).trim()) {
        link.textContent = "Túi đồ" + wanted;
      }
    }, { delay: 10000 });
  }

  window.JVRealtime = {
    poll: poll,
    liveBalance: liveBalance,
    liveBagCount: liveBagCount,
  };

  document.addEventListener("DOMContentLoaded", function () {
    liveBalance();
    liveBagCount();
  });
})();
