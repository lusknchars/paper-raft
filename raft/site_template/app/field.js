// A quiet ordered-dither field behind the page, in Paperraft's manner: a 4x4 Bayer threshold over a slow sine field.
// Drawn small and scaled up; still when the user prefers reduced motion; never blocks the page.
(function () {
  const canvas = document.getElementById("field");
  if (!canvas || !canvas.getContext) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const bayer = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const cell = 4;
  let w = 0, h = 0, img = null;
  function size() {
    w = Math.ceil(window.innerWidth / cell); h = Math.ceil(window.innerHeight / cell);
    canvas.width = w; canvas.height = h; img = ctx.createImageData(w, h);
    canvas.style.imageRendering = "pixelated";
  }
  function draw(t) {
    const d = img.data;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const v = 0.5 + 0.25 * Math.sin(x * 0.045 + t) + 0.25 * Math.sin(y * 0.06 - t * 0.7 + Math.sin(x * 0.02));
      const on = v * 16 > bayer[(y & 3) * 4 + (x & 3)];
      const k = (y * w + x) * 4;
      d[k] = 214; d[k + 1] = 150; d[k + 2] = 172; d[k + 3] = on ? 150 : 0;
    }
    ctx.putImageData(img, 0, 0);
  }
  size();
  window.addEventListener("resize", () => { size(); draw(0); });
  if (still) { draw(0); return; }
  let last = 0;
  (function loop(ms) {
    if (ms - last > 120) { draw(ms / 6000); last = ms; }  // about 8 frames a second is enough for a background
    requestAnimationFrame(loop);
  })(0);
})();
