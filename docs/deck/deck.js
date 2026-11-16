// Generates docs/sadih-deck.pptx.   npm i pptxgenjs && node docs/deck/deck.js
// The avatar is an inline SVG - PowerPoint renders SVG natively. Keep Arabic in its own text box (bidi).
const pptxgen = require("pptxgenjs");

const INK = "1E1B34", INK_SOFT = "2C2750", INK_GLOW = "272246";
const LIGHT = "F6F5FA", WHITE = "FFFFFF";
const CORAL = "FF6F5E", VIOLET = "7A5AF8";
const MUTED = "6B6689", MUTED_D = "A49FC4";
const LINE = "413A6B", HAIR = "D6D2E6";

const TF = "Arial", BF = "Calibri", AF = "Arial";
const NAME = "صادِح";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5
pres.author = NAME + " team";
pres.title = NAME;

const sh = () => ({ type: "outer", color: "C9C4DE", blur: 12, offset: 3, angle: 90, opacity: 0.4 });

// ---------- the signing avatar, as SVG (PowerPoint renders it natively) ----------
function avatarSvg(p) {
  const hand = (x, y, rot, col) => `
    <g transform="translate(${x},${y}) rotate(${rot}) scale(1.15)">
      <rect x="-26" y="-50" width="52" height="58" rx="15" fill="${col}"/>
      <rect x="-25" y="-88" width="12" height="46" rx="6" fill="${col}"/>
      <rect x="-10" y="-94" width="12" height="52" rx="6" fill="${col}"/>
      <rect x="5"   y="-92" width="12" height="50" rx="6" fill="${col}"/>
      <rect x="19"  y="-84" width="12" height="42" rx="6" fill="${col}"/>
      <rect x="-46" y="-46" width="12" height="36" rx="6" fill="${col}" transform="rotate(-38 -40 -28)"/>
    </g>`;
  const arm = pts => `<polyline points="${pts.map(q => q.join(",")).join(" ")}" fill="none" stroke="#B9B4D6" stroke-width="46" stroke-linecap="round" stroke-linejoin="round"/>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 520">
    <circle cx="200" cy="92" r="58" fill="#B9B4D6"/>
    <rect x="183" y="144" width="34" height="36" rx="10" fill="#B9B4D6"/>
    <path d="M92 214 Q92 178 128 176 L272 176 Q308 178 308 214 L298 476 Q298 506 268 506 L132 506 Q102 506 102 476 Z" fill="#8F89B8"/>
    ${arm(p.l.pts)}${arm(p.r.pts)}
    ${hand(p.l.pts[2][0], p.l.pts[2][1], p.l.rot, "#FF6F5E")}
    ${hand(p.r.pts[2][0], p.r.pts[2][1], p.r.rot, "#7A5AF8")}
  </svg>`;
}
const POSES = {
  a: { l: { pts: [[128, 226], [66, 340], [142, 296]], rot: -18 }, r: { pts: [[272, 226], [338, 300], [258, 238]], rot: 14 } },
  b: { l: { pts: [[128, 226], [74, 332], [152, 254]], rot: -8 },  r: { pts: [[272, 226], [326, 332], [248, 254]], rot: 8 } },
  c: { l: { pts: [[128, 226], [60, 336], [120, 276]], rot: -28 }, r: { pts: [[272, 226], [350, 330], [316, 292]], rot: 30 } },
};
const avatarData = k => "image/svg+xml;base64," + Buffer.from(avatarSvg(POSES[k])).toString("base64");
const AR = 400 / 520; // width per unit height
function avatar(s, k, cx, y, h) {
  s.addImage({ data: avatarData(k), x: cx - (h * AR) / 2, y, w: h * AR, h });
}

// ---------- helpers ----------
function darkBg(s) {
  s.background = { color: INK };
  s.addShape(pres.ShapeType.ellipse, { x: 10.6, y: -1.6, w: 4.6, h: 4.6, fill: { color: INK_GLOW } });
  s.addShape(pres.ShapeType.ellipse, { x: -1.5, y: 5.2, w: 3.8, h: 3.8, fill: { color: INK_GLOW } });
}
function eyebrow(s, t, x, y, c, w) {
  s.addText(t, { x, y, w: w || 5, h: 0.28, margin: 0, fontFace: BF, fontSize: 10.5, bold: true, color: c || CORAL, charSpacing: 2.6, valign: "top" });
}
function title(s, t, sub) {
  s.addText(t, { x: 0.8, y: 0.52, w: 10.5, h: 0.7, margin: 0, fontFace: TF, fontSize: 33, bold: true, color: INK, valign: "top" });
  if (sub) s.addText(sub, { x: 0.8, y: 1.3, w: 10.2, h: 0.36, margin: 0, fontFace: BF, fontSize: 14, color: MUTED, valign: "top" });
}
function mark(s) {
  s.addText(NAME, { x: 11.3, y: 6.92, w: 1.2, h: 0.34, margin: 0, fontFace: AF, fontSize: 13, bold: true, color: MUTED, align: "right", valign: "middle" });
}
function owner(s, name, x, y) {
  s.addText([{ text: "OWNER   ", options: { bold: true, color: MUTED, charSpacing: 2, fontSize: 10 } },
             { text: name, options: { bold: true, color: VIOLET, fontSize: 13 } }],
    { x, y, w: 5, h: 0.3, margin: 0, fontFace: BF, valign: "top" });
}
function chip(s, txt, x, y, w, h, fill, col, size) {
  s.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.09, fill: { color: fill }, shadow: sh() });
  s.addText(txt, { x, y, w, h, margin: 0, fontFace: AF, fontSize: size || 15, color: col, align: "center", valign: "middle" });
}
function badge(s, n, x, y, d, fill, col) {
  s.addShape(pres.ShapeType.ellipse, { x, y, w: d, h: d, fill: { color: fill } });
  s.addText(String(n), { x, y, w: d, h: d, margin: 0, fontFace: TF, fontSize: 10, bold: true, color: col, align: "center", valign: "middle" });
}

// ================= SLIDE 1 =================
{
  const s = pres.addSlide();
  darkBg(s);
  s.addText(NAME, { x: 0.8, y: 0.72, w: 3, h: 0.6, margin: 0, fontFace: AF, fontSize: 30, bold: true, color: CORAL, align: "left", valign: "top" });
  s.addText("Hand them your phone.\nRead what they say.", {
    x: 0.8, y: 1.55, w: 7.5, h: 1.85, margin: 0,
    fontFace: TF, fontSize: 38, bold: true, color: WHITE, lineSpacingMultiple: 1.06, valign: "top" });
  s.addText("Whoever is speaking talks into the phone. A 3D avatar signs it back, live.", {
    x: 0.8, y: 3.12, w: 7.1, h: 0.5, margin: 0, fontFace: BF, fontSize: 16, color: MUTED_D, valign: "top" });

  s.addShape(pres.ShapeType.roundRect, { x: 0.8, y: 4.25, w: 7.1, h: 1.5, rectRadius: 0.09, fill: { color: INK_SOFT } });
  eyebrow(s, "WHY IT IS NEEDED", 1.15, 4.55, CORAL);
  s.addText("Interpreters must be booked ahead. Most conversations never have one.", {
    x: 1.15, y: 4.92, w: 6.4, h: 0.6, margin: 0, fontFace: BF, fontSize: 15, color: WHITE, lineSpacingMultiple: 1.18, valign: "top" });

  s.addText("Hearing → Deaf. The reply path is a text and quick-response screen.", {
    x: 0.8, y: 6.25, w: 7.4, h: 0.32, margin: 0, fontFace: BF, fontSize: 11.5, italic: true, color: MUTED_D, valign: "top" });

  const px = 8.95, py = 1.35, pw = 3.4, ph = 5.55;
  s.addShape(pres.ShapeType.roundRect, { x: px, y: py, w: pw, h: ph, rectRadius: 0.11, fill: { color: INK_SOFT } });
  const sx = px + 0.18, sy = py + 0.18, sw = pw - 0.36;
  s.addShape(pres.ShapeType.roundRect, { x: sx, y: sy, w: sw, h: ph - 0.36, rectRadius: 0.09, fill: { color: "17142B" } });
  s.addShape(pres.ShapeType.roundRect, { x: sx + 0.28, y: sy + 0.3, w: 1.65, h: 0.34, rectRadius: 0.17, fill: { color: CORAL } });
  s.addText("LISTENING", { x: sx + 0.28, y: sy + 0.3, w: 1.65, h: 0.34, margin: 0,
    fontFace: BF, fontSize: 9.5, bold: true, color: WHITE, align: "center", valign: "middle", charSpacing: 1.5 });
  avatar(s, "a", sx + sw / 2, sy + 0.88, 2.8);
  s.addShape(pres.ShapeType.roundRect, { x: sx + 0.28, y: sy + 3.85, w: sw - 0.56, h: 1.0, rectRadius: 0.08, fill: { color: INK_SOFT } });
  [0.18, 0.44, 0.7].forEach((dy, i) => s.addShape(pres.ShapeType.roundRect, {
    x: sx + 0.46, y: sy + 3.85 + dy, w: [2.05, 1.75, 1.2][i], h: 0.11, rectRadius: 0.055, fill: { color: LINE } }));

  s.addNotes("Deaf-owned, not institution-owned. No booking, no procurement — the user carries it into any room.");
}

// ================= SLIDE 2 =================
{
  const s = pres.addSlide();
  s.background = { color: LIGHT };
  title(s, "The stack", "Three stages. Every one of them is a model.");

  const NW = 2.9, GP = 1.5, X0 = 0.8, NY = 2.25, NH = 2.75;
  const nx = i => X0 + i * (NW + GP), midY = NY + NH / 2;

  const wave = (cx, cy, c) => [0.3, 0.55, 0.78, 0.5, 0.26].forEach((h, i) =>
    s.addShape(pres.ShapeType.roundRect, { x: cx - 0.44 + i * 0.19, y: cy - h / 2, w: 0.1, h, rectRadius: 0.05, fill: { color: c } }));
  const lines = (cx, cy, c) => [0.98, 0.74, 0.52].forEach((w, i) =>
    s.addShape(pres.ShapeType.roundRect, { x: cx - 0.49, y: cy - 0.28 + i * 0.24, w, h: 0.12, rectRadius: 0.06, fill: { color: c } }));

  [{ n: "01", t: "Speech → Text", k: "AI MODEL", g: wave, col: VIOLET },
   { n: "02", t: "Text → Gloss", k: "AI MODEL", g: lines, col: VIOLET },
   { n: "03", t: "Gloss → Avatar", k: "GENERATED", g: null, col: CORAL }].forEach((nd, i) => {
    const x = nx(i);
    s.addShape(pres.ShapeType.roundRect, { x, y: NY, w: NW, h: NH, rectRadius: 0.1, fill: { color: INK }, shadow: sh() });
    s.addText(nd.n, { x: x + 0.3, y: NY + 0.26, w: 1.0, h: 0.32, margin: 0, fontFace: TF, fontSize: 15, bold: true, color: nd.col, valign: "top" });
    if (nd.g) nd.g(x + NW / 2, NY + 1.0, nd.col);
    else avatar(s, "a", x + NW / 2, NY + 0.36, 1.3);
    s.addText(nd.t, { x: x + 0.2, y: NY + 1.72, w: NW - 0.4, h: 0.4, margin: 0,
      fontFace: TF, fontSize: 17, bold: true, color: WHITE, align: "center", valign: "top" });
    s.addText(nd.k, { x: x + 0.2, y: NY + 2.24, w: NW - 0.4, h: 0.24, margin: 0,
      fontFace: BF, fontSize: 9, bold: true, charSpacing: 1.6, color: nd.col, align: "center", valign: "top" });
  });

  [{ l: "ARABIC TEXT", t: "وين المختبر؟" }, { l: "GLOSS", t: "مختبر  وين" }].forEach((pl, i) => {
    const gx = nx(i) + NW;
    s.addShape(pres.ShapeType.roundRect, { x: gx + 0.12, y: midY - 0.02, w: GP - 0.24, h: 0.05, rectRadius: 0.025, fill: { color: HAIR } });
    s.addText("→", { x: gx, y: midY - 0.95, w: GP, h: 0.4, margin: 0, fontFace: TF, fontSize: 17, bold: true, color: VIOLET, align: "center", valign: "middle" });
    chip(s, pl.t, gx + 0.1, midY - 0.5, GP - 0.2, 0.44, WHITE, INK, 12);
    s.addText(pl.l, { x: gx, y: midY + 0.16, w: GP, h: 0.26, margin: 0,
      fontFace: BF, fontSize: 8.5, bold: true, charSpacing: 1.2, color: MUTED, align: "center", valign: "top" });
  });

  [["1–2 sec", "behind the speaker"], ["Any word", "composed or fingerspelled"], ["No pauses", "we cut on clauses"]]
    .forEach((f, i) => {
      const x = 0.8 + i * 4.05;
      s.addText(f[0], { x, y: 5.75, w: 3.75, h: 0.45, margin: 0, fontFace: TF, fontSize: 23, bold: true, color: VIOLET, valign: "top" });
      s.addText(f[1], { x, y: 6.25, w: 3.75, h: 0.3, margin: 0, fontFace: BF, fontSize: 12, color: MUTED, valign: "top" });
    });

  mark(s);
  s.addNotes("Walk the example along the arrows. Arabic asks 'where is the lab' — the gloss puts the topic first because that is sign order.");
}

// ================= SLIDE 3 =================
{
  const s = pres.addSlide();
  s.background = { color: LIGHT };
  title(s, "01   Speech → Text", "People do not pause. So we cut on grammar, not on silence.");

  const WX = 0.9, WW = 11.5, WY = 2.95;
  eyebrow(s, "CONTINUOUS SPEECH", WX, 2.3, MUTED, 2.6);

  const n = 74, step = WW / n;
  for (let i = 0; i < n; i++) {
    const h = 0.16 + 0.62 * Math.abs(Math.sin(i * 0.9) * Math.cos(i * 0.31));
    s.addShape(pres.ShapeType.roundRect, {
      x: WX + i * step, y: WY - h / 2, w: step * 0.55, h, rectRadius: step * 0.28, fill: { color: VIOLET } });
  }
  const cuts = [0.30, 0.58, 0.83];
  cuts.forEach(f => {
    const x = WX + WW * f;
    s.addShape(pres.ShapeType.roundRect, { x: x - 0.025, y: WY - 0.72, w: 0.05, h: 1.44, rectRadius: 0.025, fill: { color: CORAL } });
    s.addShape(pres.ShapeType.ellipse, { x: x - 0.09, y: WY - 0.9, w: 0.18, h: 0.18, fill: { color: CORAL } });
  });
  const bounds = [0, ...cuts, 1];
  ["أمس رحت للمستشفى", "وقابلت الدكتور", "وقال التحاليل طبيعية", "ولازم أرجع بعدين"].forEach((t, i) => {
    const a = WX + WW * bounds[i], b = WX + WW * bounds[i + 1];
    chip(s, t, a + 0.07, 4.3, (b - a) - 0.14, 0.6, WHITE, INK, 12.5);
    badge(s, i + 1, a + 0.19, 4.2, 0.3, VIOLET, WHITE);
  });

  s.addText("A clause boundary lands every two to four seconds. We never wait for silence.", {
    x: 0.9, y: 5.3, w: 11.5, h: 0.35, margin: 0, fontFace: BF, fontSize: 14, color: MUTED, valign: "top" });
  [["~600 ms", "stability window before a word is committed"],
   ["Stable prefix only", "a revised word is never signed twice"]].forEach((f, i) => {
    const x = 0.9 + i * 5.9;
    s.addText(f[0], { x, y: 5.95, w: 5.5, h: 0.4, margin: 0, fontFace: TF, fontSize: 20, bold: true, color: VIOLET, valign: "top" });
    s.addText(f[1], { x, y: 6.4, w: 5.5, h: 0.3, margin: 0, fontFace: BF, fontSize: 12, color: MUTED, valign: "top" });
  });

  owner(s, "Ziyad", 0.9, 6.95);
  mark(s);
  s.addNotes("Silence-based segmentation breaks the moment someone talks like a person. Conjunctions and discourse markers give us the cut.");
}

// ================= SLIDE 4 =================
{
  const s = pres.addSlide();
  s.background = { color: LIGHT };
  title(s, "02   Text → Gloss", "Arabic word order in. Sign order out.");

  const CW = 2.1, GAP = 0.35, RIGHT = 11.375;
  const px = i => RIGHT - CW - i * (CW + GAP);

  eyebrow(s, "ARABIC", 0.9, 2.77, MUTED, 1.2);
  ["أنا", "رحت", "للمستشفى", "أمس"].forEach((w, i) => {
    chip(s, w, px(i), 2.55, CW, 0.72, WHITE, INK, 16);
    badge(s, i + 1, px(i) + CW - 0.44, 2.43, 0.32, MUTED, WHITE);
  });
  s.addText("↓", { x: 0, y: 3.45, w: 13.3, h: 0.5, margin: 0, fontFace: TF, fontSize: 22, bold: true, color: VIOLET, align: "center", valign: "middle" });

  s.addShape(pres.ShapeType.roundRect, { x: px(0), y: 4.12, w: CW - 0.58, h: 0.26, rectRadius: 0.13, fill: { color: CORAL } });
  s.addText("TOPIC", { x: px(0), y: 4.12, w: CW - 0.58, h: 0.26, margin: 0,
    fontFace: BF, fontSize: 8.5, bold: true, color: WHITE, align: "center", valign: "middle", charSpacing: 1.4 });

  eyebrow(s, "GLOSS", 0.9, 4.66, MUTED, 1.2);
  [["أمس", 4], ["مستشفى", 3], ["أنا", 1], ["روح", 2]].forEach((p, i) => {
    chip(s, p[0], px(i), 4.44, CW, 0.72, INK, WHITE, 16);
    badge(s, p[1], px(i) + CW - 0.44, 4.32, 0.32, CORAL, WHITE);
  });

  s.addText("Time moves to the front. Function words drop. Verbs go back to their base form.", {
    x: 0.9, y: 5.55, w: 11.5, h: 0.35, margin: 0, fontFace: BF, fontSize: 14, color: MUTED, valign: "top" });
  s.addText("The badges show where each word ended up.", {
    x: 0.9, y: 5.95, w: 7, h: 0.3, margin: 0, fontFace: BF, fontSize: 12, italic: true, color: MUTED, valign: "top" });

  owner(s, "Raid", 0.9, 6.5);
  mark(s);
  s.addNotes("Point at the badges. Word 4 leads, word 1 lands third. A dictionary cannot do that — it needs a language model.");
}

// ================= SLIDE 5 =================
{
  const s = pres.addSlide();
  s.background = { color: LIGHT };
  title(s, "03   Gloss → Avatar", "The motion is generated. There is no clip library anywhere.");

  eyebrow(s, "GLOSS IN", 0.9, 2.35, MUTED, 3);
  ["أمس", "مستشفى", "روح"].forEach((w, i) => chip(s, w, 0.9, 2.75 + i * 0.78, 2.3, 0.62, INK, WHITE, 15));

  s.addText("→", { x: 3.35, y: 3.6, w: 0.7, h: 0.5, margin: 0, fontFace: TF, fontSize: 20, bold: true, color: VIOLET, align: "center", valign: "middle" });

  eyebrow(s, "MOTION TOKENS", 4.2, 2.35, MUTED, 3);
  const TS = 0.3, TG = 0.09;
  for (let r = 0; r < 3; r++) for (let c = 0; c < 9; c++) {
    s.addShape(pres.ShapeType.roundRect, {
      x: 4.2 + c * (TS + TG), y: 2.78 + r * (TS + TG), w: TS, h: TS, rectRadius: 0.07,
      fill: { color: (r * 9 + c) % 3 === 0 ? CORAL : VIOLET } });
  }
  s.addText("~8 per second of signing", { x: 4.2, y: 4.1, w: 3.5, h: 0.3, margin: 0, fontFace: BF, fontSize: 11.5, color: MUTED, valign: "top" });

  s.addText("→", { x: 7.9, y: 3.6, w: 0.7, h: 0.5, margin: 0, fontFace: TF, fontSize: 20, bold: true, color: VIOLET, align: "center", valign: "middle" });

  eyebrow(s, "GENERATED FRAMES", 8.75, 2.35, MUTED, 3.5);
  s.addShape(pres.ShapeType.roundRect, { x: 8.75, y: 2.72, w: 3.65, h: 1.75, rectRadius: 0.09, fill: { color: INK } });
  ["a", "b", "c"].forEach((k, i) => avatar(s, k, 8.75 + 3.65 * (1 + 2 * i) / 6, 2.85, 1.5));

  [["Motion becomes tokens", "A residual VQ-VAE compresses pose. Hands get their own codebook."],
   ["Left to right, not diffusion", "The avatar starts moving before the sentence is finished."],
   ["Trained on Saudi signing", "Isharah-500, with SMPL-X labels from Tamaththul3D."]]
   .forEach((f, i) => {
     const x = [0.9, 4.2, 8.75][i], cw2 = [3.0, 3.55, 3.65][i];
     s.addText(f[0], { x, y: 5.1, w: cw2, h: 0.32, margin: 0, fontFace: TF, fontSize: 14.5, bold: true, color: INK, valign: "top" });
     s.addText(f[1], { x, y: 5.47, w: cw2, h: 0.7, margin: 0, fontFace: BF, fontSize: 12, color: MUTED, lineSpacingMultiple: 1.14, valign: "top" });
   });

  owner(s, "Nawaf", 0.9, 6.95);
  mark(s);
  s.addNotes("Diffusion would denoise the whole clip before anything plays. Autoregressive tokens stream, so playback starts early — the real-time requirement forces this choice.");
}

// ================= SLIDE 6 — same frame as slide 5 =================
{
  const s = pres.addSlide();
  s.background = { color: LIGHT };
  title(s, "The team", "Five people. Three own a stage, two span all of them.");

  const NW = 3.45, GAP = 0.575, X0 = 0.9;
  const nx = i => X0 + i * (NW + GAP);
  const CY = 2.35, RY = 3.22, RH = 1.15;

  [["Ziyad", "Speech → Text"], ["Raid", "Text → Gloss"], ["Nawaf", "Gloss → Avatar"]].forEach((p, i) => {
    const x = nx(i), cx = x + NW / 2;
    s.addShape(pres.ShapeType.ellipse, { x: cx - 0.36, y: CY, w: 0.72, h: 0.72, fill: { color: CORAL } });
    s.addText(p[0].charAt(0), { x: cx - 0.36, y: CY, w: 0.72, h: 0.72, margin: 0,
      fontFace: TF, fontSize: 19, bold: true, color: INK, align: "center", valign: "middle" });
    s.addShape(pres.ShapeType.roundRect, { x, y: RY, w: NW, h: RH, rectRadius: 0.09, fill: { color: INK }, shadow: sh() });
    s.addText(p[0], { x, y: RY + 0.2, w: NW, h: 0.34, margin: 0,
      fontFace: TF, fontSize: 17, bold: true, color: WHITE, align: "center", valign: "top" });
    s.addText(p[1], { x, y: RY + 0.62, w: NW, h: 0.32, margin: 0,
      fontFace: BF, fontSize: 13, color: MUTED_D, align: "center", valign: "top" });
    if (i < 2) s.addText("→", { x: x + NW, y: RY + 0.35, w: GAP, h: 0.45, margin: 0,
      fontFace: TF, fontSize: 17, bold: true, color: VIOLET, align: "center", valign: "middle" });
  });

  const FULL = nx(2) + NW - X0;
  [["Mohammed", "Backend", "streaming service  ·  GPU inference  ·  token stream"],
   ["Sultan", "Mobile & Frontend", "the app  ·  avatar view  ·  live text track"]].forEach((p, i) => {
    const y = 4.72 + i * 0.92;
    s.addShape(pres.ShapeType.roundRect, { x: X0, y, w: FULL, h: 0.76, rectRadius: 0.09, fill: { color: WHITE }, shadow: sh() });
    s.addShape(pres.ShapeType.ellipse, { x: X0 + 0.3, y: y + 0.16, w: 0.44, h: 0.44, fill: { color: VIOLET } });
    s.addText(p[0].charAt(0), { x: X0 + 0.3, y: y + 0.16, w: 0.44, h: 0.44, margin: 0,
      fontFace: TF, fontSize: 13, bold: true, color: WHITE, align: "center", valign: "middle" });
    s.addText(p[0], { x: X0 + 0.98, y, w: 2.2, h: 0.76, margin: 0, fontFace: TF, fontSize: 15, bold: true, color: INK, valign: "middle" });
    s.addText(p[1], { x: X0 + 3.2, y, w: 2.6, h: 0.76, margin: 0, fontFace: BF, fontSize: 13, bold: true, color: VIOLET, valign: "middle" });
    s.addText(p[2], { x: X0 + 5.9, y, w: FULL - 6.2, h: 0.76, margin: 0, fontFace: BF, fontSize: 12.5, color: MUTED, valign: "middle" });
  });

  s.addText("First milestone: hand over the phone and watch the avatar sign a generated sentence back.", {
    x: 0.9, y: 6.72, w: 9.5, h: 0.34, margin: 0, fontFace: BF, fontSize: 12.5, italic: true, color: MUTED, valign: "top" });
  mark(s);
  s.addNotes("Three people own a pipeline stage each. Mohammed and Sultan span every stage.");
}

const OUT = require("path").join(__dirname, "..", "sadih-deck.pptx");   // docs/sadih-deck.pptx
pres.writeFile({ fileName: OUT }).then(() => console.log("wrote " + OUT));
