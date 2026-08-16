/**
 * The five product cards that float behind the v5 hero, drawn to 2D canvases.
 *
 * Ported from `_heroCardTex` in `Sapling Landing v5.dc.html`. Each card is
 * painted once into an offscreen canvas and handed to three.js as a texture,
 * so the "UI" in the hero is pixels, not DOM — it costs one draw at mount and
 * nothing per frame.
 *
 * The canvas is deliberately larger than the card: a 56px margin all round
 * gives the drop shadow room to fall without being clipped by the texture
 * edge. That margin is why the plane's aspect is 692/572 rather than 580/460.
 *
 * Type sizes here are NOT free. The 460px-wide card body projects to roughly
 * 230 CSS px on the near panels and 200 on the far ones, so everything drawn
 * here lands at about half the size it reads at in this file. Anything under
 * ~18px ends up below 9 CSS px on screen, where a one-pixel stroke covers less
 * than half a device pixel and averages away into the card — which is what
 * made the earlier 15px micro-copy look blurred and washed out rather than
 * small. Treat 18px as the floor, and keep the micro-greys dark enough that a
 * half-covered pixel still separates from #FDFCF9.
 */

/** Card body, in canvas units. */
const W = 460;
const H = 580;
/** Bleed around the card, so the shadow isn't clipped. */
const M = 56;
const DPR = 2;
/** Left text margin inside the card. */
const P = 34;

export const CARD_W = W + M * 2; // 572
export const CARD_H = H + M * 2; // 692

const SANS = "'DM Sans',system-ui,sans-serif";
const MONO = "'JetBrains Mono',monospace";
const SERIF = "'Spectral',Georgia,serif";
const INK = '#12201A';
const DIM = '#65736B';
/** The lightest grey that still survives the downscale, for meta lines. */
const FAINT = '#7E8C85';
const LINE = 'rgba(20,45,32,0.10)';

export type CardKind = 0 | 1 | 2 | 3 | 4;

/**
 * Draws one card and returns its canvas.
 *
 * Call again once webfonts have loaded — the first paint can land before
 * DM Sans / Spectral / JetBrains Mono are ready, and the metrics differ
 * enough that the wrapped copy re-flows.
 */
export function drawHeroCard(kind: CardKind): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = CARD_W * DPR;
  c.height = CARD_H * DPR;
  const x = c.getContext('2d');
  if (!x) return c;
  x.scale(DPR, DPR);
  x.translate(M, M);

  /** Rounded rect path. */
  const rr = (a: number, b: number, w: number, h: number, r: number) => {
    x.beginPath();
    x.moveTo(a + r, b);
    x.arcTo(a + w, b, a + w, b + h, r);
    x.arcTo(a + w, b + h, a, b + h, r);
    x.arcTo(a, b + h, a, b, r);
    x.arcTo(a, b, a + w, b, r);
    x.closePath();
  };

  // card body — filled twice: once to cast the shadow, once opaque over it
  x.save();
  x.shadowColor = 'rgba(18,45,32,0.24)';
  x.shadowBlur = 46;
  x.shadowOffsetY = 18;
  x.fillStyle = '#FDFCF9';
  rr(0, 0, W, H, 30);
  x.fill();
  x.restore();
  x.fillStyle = '#FDFCF9';
  rr(0, 0, W, H, 30);
  x.fill();
  x.strokeStyle = 'rgba(20,45,32,0.13)';
  x.lineWidth = 2;
  rr(1, 1, W - 2, H - 2, 30);
  x.stroke();

  const eyebrow = (t: string, y: number, col?: string) => {
    x.font = '600 20px ' + MONO;
    x.fillStyle = col || FAINT;
    x.letterSpacing = '2.2px';
    x.fillText(t, P, y);
    x.letterSpacing = '0px';
  };

  const wrap = (t: string, y: number, max: number, lh: number, font: string, col: string) => {
    x.font = font;
    x.fillStyle = col;
    let line = '';
    let yy = y;
    for (const w of t.split(' ')) {
      const test = line ? line + ' ' + w : w;
      if (x.measureText(test).width > max && line) {
        x.fillText(line, P, yy);
        yy += lh;
        line = w;
      } else line = test;
    }
    if (line) x.fillText(line, P, yy);
    return yy + lh;
  };

  const bar = (y: number, label: string, pct: number, col: string) => {
    x.font = '500 20px ' + SANS;
    x.fillStyle = DIM;
    x.fillText(label, P, y);
    x.fillStyle = '#E9E5DA';
    rr(P, y + 12, W - P * 2, 9, 5);
    x.fill();
    x.fillStyle = col;
    rr(P, y + 12, (W - P * 2) * pct, 9, 5);
    x.fill();
  };

  if (kind === 0) {
    // ── course mastery ──
    eyebrow('PY 205 · MECHANICS', 54);
    x.font = '700 46px ' + SERIF;
    x.fillStyle = '#1B6C42';
    x.fillText('61%', P, 116);
    x.font = '500 20px ' + SANS;
    x.fillStyle = DIM;
    x.fillText('course mastery', P + 100, 114);
    bar(180, 'Kinematics', 0.84, '#3A7D4E');
    bar(252, 'Momentum', 0.52, '#4FA574');
    bar(324, 'Rotational torque', 0.21, '#C89B5E');
    bar(396, 'Oscillation', 0.07, '#B25855');
    x.strokeStyle = LINE;
    x.beginPath();
    x.moveTo(P, 468);
    x.lineTo(W - P, 468);
    x.stroke();
    x.font = '500 20px ' + SANS;
    x.fillStyle = DIM;
    x.fillText('Next review · 14 cards due', P, 502);
  } else if (kind === 1) {
    // ── flashcard ──
    eyebrow('CARD 03 / 12', 54);
    x.fillStyle = '#B25855';
    x.beginPath();
    x.arc(W - P - 7, 48, 7, 0, 6.3);
    x.fill();
    x.fillStyle = '#F2F5EF';
    rr(P, 90, W - P * 2, 230, 20);
    x.fill();
    x.strokeStyle = LINE;
    x.lineWidth = 2;
    rr(P + 1, 91, W - P * 2 - 2, 228, 20);
    x.stroke();
    x.font = '500 18px ' + MONO;
    x.fillStyle = FAINT;
    x.letterSpacing = '2.6px';
    x.fillText('FRONT', P + 26, 126);
    x.letterSpacing = '0px';
    x.save();
    x.translate(-8, 0);
    wrap('What does the damping constant scale?', 178, W - P * 2 - 40, 42, '600 32px ' + SERIF, INK);
    x.restore();
    const chips: [string, string][] = [
      ['Forgot', 'rgba(178,88,85,0.5)'],
      ['Hard', 'rgba(200,155,94,0.55)'],
      ['Easy', 'rgba(58,125,78,0.6)'],
    ];
    const cw = (W - P * 2 - 20) / 3;
    chips.forEach((ch, i) => {
      const cx0 = P + i * (cw + 10);
      x.strokeStyle = ch[1];
      x.lineWidth = 2;
      rr(cx0, 360, cw, 54, 12);
      x.stroke();
      x.font = '500 21px ' + SANS;
      x.fillStyle = DIM;
      x.textAlign = 'center';
      x.fillText(ch[0], cx0 + cw / 2, 394);
      x.textAlign = 'left';
    });
    x.font = '500 20px ' + MONO;
    x.fillStyle = FAINT;
    x.fillText('next in 4d · 12d · 31d', P, 468);
    x.strokeStyle = LINE;
    x.lineWidth = 2;
    x.beginPath();
    x.moveTo(P, 496);
    x.lineTo(W - P, 496);
    x.stroke();
    x.font = '500 20px ' + SANS;
    x.fillStyle = DIM;
    x.fillText('From: Lecture 9 notes.pdf', P, 530);
  } else if (kind === 2) {
    // ── adaptive quiz ──
    eyebrow('ADAPTIVE QUIZ · CH 4', 54);
    wrap(
      'A block slides down a frictionless incline. Which quantity is conserved?',
      106, W - P * 2, 38, '600 29px ' + SERIF, INK,
    );
    const opts: [string, number][] = [
      ['Momentum along the slope', 0],
      ['Mechanical energy', 1],
      ['Normal force', 0],
    ];
    opts.forEach((o, i) => {
      const y = 268 + i * 74;
      x.fillStyle = o[1] ? 'rgba(58,125,78,0.09)' : '#F2F5EF';
      rr(P, y, W - P * 2, 58, 14);
      x.fill();
      x.strokeStyle = o[1] ? 'rgba(58,125,78,0.55)' : LINE;
      x.lineWidth = 2;
      rr(P + 1, y + 1, W - P * 2 - 2, 56, 14);
      x.stroke();
      x.font = '500 21px ' + SANS;
      x.fillStyle = o[1] ? '#1B6C42' : DIM;
      x.fillText(o[0], P + 24, y + 37);
      if (o[1]) {
        x.strokeStyle = '#3A7D4E';
        x.lineWidth = 3.4;
        x.lineCap = 'round';
        x.beginPath();
        x.moveTo(W - P - 44, y + 29);
        x.lineTo(W - P - 34, y + 39);
        x.lineTo(W - P - 16, y + 19);
        x.stroke();
      }
    });
    x.font = '500 20px ' + MONO;
    x.fillStyle = FAINT;
    x.fillText('DIFFICULTY ↑  ·  4 OF 8', P, 512);
  } else if (kind === 3) {
    // ── mini knowledge graph ──
    eyebrow('KNOWLEDGE GRAPH', 54);
    const nodes: [number, number, number, string][] = [
      [230, 210, 26, '#3A7D4E'], [130, 140, 13, '#4FA574'], [330, 145, 12, '#C89B5E'],
      [110, 300, 11, '#B25855'], [340, 300, 14, '#4FA574'], [230, 360, 10, '#9A9A9A'],
      [180, 250, 8, '#3A7D4E'], [300, 235, 9, '#C89B5E'],
    ];
    x.strokeStyle = 'rgba(27,108,66,0.26)';
    x.lineWidth = 2;
    const edges = [[0, 1], [0, 2], [0, 3], [0, 4], [0, 5], [0, 6], [0, 7], [1, 6], [2, 7], [3, 5]];
    edges.forEach((e) => {
      x.beginPath();
      x.moveTo(nodes[e[0]][0], nodes[e[0]][1]);
      x.lineTo(nodes[e[1]][0], nodes[e[1]][1]);
      x.stroke();
    });
    nodes.forEach((n) => {
      // '2A' is a hex alpha suffix — the halo is the node colour at ~16%
      x.fillStyle = n[3] + '2A';
      x.beginPath();
      x.arc(n[0], n[1], n[2] + 8, 0, 6.3);
      x.fill();
      x.fillStyle = n[3];
      x.beginPath();
      x.arc(n[0], n[1], n[2], 0, 6.3);
      x.fill();
    });
    x.strokeStyle = LINE;
    x.lineWidth = 2;
    x.beginPath();
    x.moveTo(P, 440);
    x.lineTo(W - P, 440);
    x.stroke();
    const leg: [string, string][] = [
      ['Mastered', '#3A7D4E'], ['Learning', '#4FA574'], ['Needs work', '#B25855'],
    ];
    leg.forEach((l, i) => {
      const y = 478 + i * 34;
      x.fillStyle = l[1];
      x.beginPath();
      x.arc(P + 6, y - 5, 6, 0, 6.3);
      x.fill();
      x.font = '500 20px ' + SANS;
      x.fillStyle = DIM;
      x.fillText(l[0], P + 24, y);
    });
  } else {
    // ── week calendar ──
    eyebrow('THIS WEEK', 54);
    const days = ['M', 'T', 'W', 'T', 'F'];
    const cw = (W - P * 2) / 5;
    days.forEach((d, i) => {
      x.font = '500 20px ' + MONO;
      x.fillStyle = FAINT;
      x.textAlign = 'center';
      x.fillText(d, P + cw * i + cw / 2, 106);
      x.textAlign = 'left';
    });
    x.strokeStyle = LINE;
    x.lineWidth = 2;
    x.beginPath();
    x.moveTo(P, 126);
    x.lineTo(W - P, 126);
    x.stroke();
    const evts: [string, string, number][] = [
      ['PY 205 · Problem set', '#3A7D4E', 0.72],
      ['CS 111 · Midterm', '#B25855', 1],
      ['Review · 22 cards', '#C89B5E', 0.5],
      ['EC 101 · Reading', '#4FA574', 0.34],
    ];
    evts.forEach((e, i) => {
      const y = 158 + i * 84;
      x.fillStyle = '#F2F5EF';
      rr(P, y, W - P * 2, 66, 14);
      x.fill();
      x.fillStyle = e[1];
      rr(P, y, 5, 66, 3);
      x.fill();
      x.font = '500 21px ' + SANS;
      x.fillStyle = INK;
      x.fillText(e[0], P + 22, y + 30);
      x.fillStyle = '#E9E5DA';
      rr(P + 22, y + 43, W - P * 2 - 44, 7, 4);
      x.fill();
      x.fillStyle = e[1];
      rr(P + 22, y + 43, (W - P * 2 - 44) * e[2], 7, 4);
      x.fill();
    });
    x.font = '500 20px ' + MONO;
    x.fillStyle = FAINT;
    x.fillText('PULLED FROM SYLLABUS', P, 532);
  }

  return c;
}
