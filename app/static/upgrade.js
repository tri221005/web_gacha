const SIZE = 200;
const CENTER = SIZE / 2;
const RADIUS = 82;
const STROKE = 14;
const CIRC = 2 * Math.PI * RADIUS;
const SPIN_MS = 3600;
const TURNS = 4;

export function mountGauge(el) {
  el.innerHTML = `<div class="relative" style="width:${SIZE}px;height:${SIZE}px;position:relative">
    <svg width="${SIZE}" height="${SIZE}" style="transform:rotate(-90deg)">
      <circle cx="${CENTER}" cy="${CENTER}" r="${RADIUS}" fill="none" stroke="#262626" stroke-width="${STROKE}"></circle>
      <circle id="win-arc" cx="${CENTER}" cy="${CENTER}" r="${RADIUS}" fill="none" stroke="#10b981" stroke-width="${STROKE}" stroke-dasharray="0 ${CIRC}"></circle>
    </svg>
    <div id="needle" style="position:absolute;inset:0;display:flex;align-items:flex-start;justify-content:center">
      <div style="margin-top:6px;width:0;height:0;border-left:8px solid transparent;border-right:8px solid transparent;border-top:22px solid #fbbf24"></div>
    </div>
    <div id="gauge-label" style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center">
      <span style="font-size:28px;font-weight:700;color:#34d399">0.0%</span>
      <span style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:hsl(var(--text-faint))">Tỉ lệ</span>
    </div>
  </div>`;

  const arc = el.querySelector("#win-arc");
  const needle = el.querySelector("#needle");
  const label = el.querySelector("#gauge-label");
  let chance = 0;

  return {
    setChance(value) {
      chance = Math.max(0, Math.min(0.85, value));
      const win = chance * CIRC;
      arc.setAttribute("stroke-dasharray", `${win} ${CIRC - win}`);
      label.innerHTML = `<span style="font-size:28px;font-weight:700;color:#34d399">${(chance * 100).toFixed(1)}%</span>
        <span style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:hsl(var(--text-faint))">Tỉ lệ</span>`;
      needle.style.transition = "none";
      needle.style.transform = "rotate(0deg)";
    },
    spin({ won, roll }, onEnd) {
      const angle = TURNS * 360 + roll * 360;
      needle.style.transition = "none";
      needle.style.transform = "rotate(0deg)";
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          needle.style.transition = `transform ${SPIN_MS}ms cubic-bezier(0.12, 0.78, 0.1, 1)`;
          needle.style.transform = `rotate(${angle}deg)`;
        });
      });
      setTimeout(() => {
        label.innerHTML = won
          ? `<span style="font-size:22px;font-weight:700;color:#34d399">Thắng</span>`
          : `<span style="font-size:22px;font-weight:700;color:#f87171">Trượt</span>`;
        onEnd?.();
      }, SPIN_MS);
    },
  };
}
