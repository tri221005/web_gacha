const GAP = 8;
const STRIP_LENGTH = 60;
const WINNER_INDEX = 52;
export const SPIN_MS = 5200;
const STAGGER_MS = 260;

/* Tile size follows the reel it lives in, so a 320px phone shows two
   readable tiles instead of one cropped one, and a wide screen keeps the
   generous 148px tile. The vertical reel derives from its height. */
function tileSize(horizontal, viewportEl) {
  if (horizontal) {
    const w = viewportEl.clientWidth || 320;
    return Math.round(Math.max(92, Math.min(148, w / 2.6)));
  }
  const h = viewportEl.clientHeight || 320;
  return Math.round(Math.max(84, Math.min(116, h / 2.8)));
}

function buildStrip(pool, winner) {
  const tiles = [];
  for (let i = 0; i < STRIP_LENGTH; i += 1) {
    tiles.push(pool[Math.floor(Math.random() * pool.length)]);
  }
  tiles[WINNER_INDEX] = winner;
  return tiles;
}

function tileHtml(item, horizontal, size) {
  const color = item.color || "#b0c3d9";
  const src = item.image || "/static/items/_placeholder.svg";
  const w = horizontal ? size : "86%";
  const h = horizontal ? Math.round(size * 0.95) : size;
  return `<div class="tile" data-id="${item.id}" style="border-bottom-color:${color};width:${typeof w === "number" ? w + "px" : w};height:${h}px;flex:0 0 ${typeof w === "number" ? w + "px" : "auto"}">
    <img src="${src}" alt="${item.name}" draggable="false" loading="eager">
    <span>${item.name}</span>
  </div>`;
}

export function spinReel({ pool, winner, onFinish, viewport, strip, orientation = "horizontal", index = 0 }) {
  const viewportEl = viewport || document.getElementById("reel");
  const stripEl = strip || document.getElementById("reel-strip");
  if (!viewportEl || !stripEl || !winner || !pool.length) return;

  const horizontal = orientation !== "vertical";
  const tile = tileSize(horizontal, viewportEl);
  const stride = tile + GAP;
  const duration = SPIN_MS + index * STAGGER_MS;
  const tiles = buildStrip(pool, winner);

  stripEl.className = horizontal ? "reel-strip" : "reel-strip vertical";
  stripEl.innerHTML = tiles.map((item) => tileHtml(item, horizontal, tile)).join("");
  stripEl.style.transition = "none";
  stripEl.style.transform = "translate3d(0,0,0)";
  viewportEl.style.borderColor = "";
  viewportEl.style.boxShadow = "";
  // The vertical reel's height comes from CSS (a fluid clamp), so the
  // tile size can be derived from it on every spin.

  const jitter = (Math.random() - 0.5) * (tile * 0.22);
  const size = horizontal ? viewportEl.clientWidth : viewportEl.clientHeight;
  const target = WINNER_INDEX * stride + tile / 2 - size / 2 + jitter;

  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      stripEl.style.transition = `transform ${duration}ms cubic-bezier(0.10, 0.82, 0.12, 1)`;
      stripEl.style.transform = horizontal
        ? `translate3d(${-target}px, 0, 0)`
        : `translate3d(0, ${-target}px, 0)`;
    });
  });

  window.setTimeout(() => {
    stripEl.style.transition = "none";
    stripEl.style.transform = horizontal
      ? `translate3d(${-target}px, 0, 0)`
      : `translate3d(0, ${-target}px, 0)`;
    const nodes = stripEl.querySelectorAll(".tile");
    nodes.forEach((node, i) => {
      node.classList.toggle("win", i === WINNER_INDEX);
      node.classList.toggle("dim", i !== WINNER_INDEX);
    });
    viewportEl.style.borderColor = winner.color;
    viewportEl.style.boxShadow = `0 0 26px -6px ${winner.color}`;
    onFinish?.(winner);
  }, duration);
}
