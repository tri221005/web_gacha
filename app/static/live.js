function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll('"', "&quot;");
}

function dropCard(drop) {
  return `<article class="live-card" style="border-top-color:${esc(drop.color)}">
    <img src="${esc(drop.image)}" alt="">
    <div class="name" title="${esc(drop.name)}">${esc(drop.name)}</div>
    <em class="price">${esc(drop.value_fmt)} Coin</em>
    <div class="who" title="${esc(drop.player)}">${esc(drop.player)}${drop.is_bot ? " · bot" : ""}</div>
  </article>`;
}

function bestCard(drop) {
  if (!drop) return "";
  const colour = drop.color || "#fbbf24";
  return `<aside class="live-best" style="background:linear-gradient(90deg, ${colour}33, ${colour}0d);box-shadow:inset 0 0 0 1px ${colour}59">
    <div>
      <div class="kicker" style="color:${colour}">Best of day</div>
      <div class="who">${esc(drop.player)}</div>
      <div class="name">${esc(drop.name)}</div>
      <div class="price">${esc(drop.value_fmt)} Coin</div>
    </div>
    <img src="${esc(drop.image)}" alt="">
  </aside>`;
}

async function paintDrops() {
  const el = document.getElementById("live-drops");
  if (!el) return;
  try {
    const res = await fetch("/api/drops");
    if (!res.ok) return;
    const data = await res.json();
    el.innerHTML = bestCard(data.best) + `<div class="live-row">${(data.drops || []).map(dropCard).join("")}</div>`;
  } catch (err) {
    /* ignore */
  }
}

paintDrops();
setInterval(paintDrops, 2000);
