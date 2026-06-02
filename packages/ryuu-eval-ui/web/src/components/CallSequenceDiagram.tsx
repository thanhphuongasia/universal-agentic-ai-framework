type CallEdge = { from_class: string; to_class: string; to_method: string };

const GAP = 24;   // gap between boxes
const ROW_H = 42; // height per call row
const BOX_H = 28;
const PAD_X = 8;
const PAD_Y = 8;
const LIFELINE_Y = PAD_Y + BOX_H + 4;

// Box width is sized to its full label so names are never truncated.
const CHAR_W = 6.2;     // ~width of one 10px monospace glyph
const BOX_PAD_X = 18;   // horizontal padding inside a box
const MIN_W = 64;

function boxWidth(label: string) {
  return Math.max(MIN_W, Math.ceil(label.length * CHAR_W + BOX_PAD_X));
}

export function CallSequenceDiagram({
  subgraph,
}: {
  subgraph: Record<string, CallEdge[]>;
}) {
  const calls = Object.values(subgraph).flat();
  if (!calls.length) return null;

  // Ordered unique participants
  const seen = new Set<string>();
  const participants: string[] = [];
  for (const c of calls) {
    if (!seen.has(c.from_class)) { seen.add(c.from_class); participants.push(c.from_class); }
    if (!seen.has(c.to_class))   { seen.add(c.to_class);   participants.push(c.to_class);   }
  }

  // Variable-width layout: each box as wide as its label needs.
  const widths = participants.map(boxWidth);
  const lefts: number[] = [];
  let acc = PAD_X;
  for (let i = 0; i < participants.length; i++) { lefts[i] = acc; acc += widths[i] + GAP; }
  const centers = participants.map((_, i) => lefts[i] + widths[i] / 2);

  const idxOf = (name: string) => participants.indexOf(name);
  const xCenter = (name: string) => centers[idxOf(name)];
  const n = participants.length;
  const svgW = lefts[n - 1] + widths[n - 1] + PAD_X;
  const svgH = LIFELINE_Y + calls.length * ROW_H + PAD_Y + 10;

  return (
    <div className="overflow-x-auto rounded-lg bg-gray-950 p-2">
      <svg width={svgW} height={svgH} className="block">

        {/* ── Participant boxes + lifelines ── */}
        {participants.map((p, i) => {
          const cx = centers[i];
          const bx = lefts[i];
          return (
            <g key={p}>
              <rect x={bx} y={PAD_Y} width={widths[i]} height={BOX_H} rx={3}
                fill="#1f2937" stroke="#374151" strokeWidth={1} />
              <title>{p}</title>
              <text x={cx} y={PAD_Y + BOX_H / 2 + 4} textAnchor="middle"
                fill="#d1d5db" fontSize={10} fontFamily="ui-monospace,monospace">
                {p}
              </text>
              <line x1={cx} y1={LIFELINE_Y} x2={cx} y2={svgH - PAD_Y}
                stroke="#374151" strokeWidth={1} strokeDasharray="4,3" />
            </g>
          );
        })}

        {/* ── Call arrows ── */}
        {calls.map((call, i) => {
          const y = LIFELINE_Y + i * ROW_H + ROW_H * 0.58;
          const x1 = xCenter(call.from_class);
          const x2 = xCenter(call.to_class);
          const label = `${call.to_method}()`;

          // Self-call
          if (x1 === x2) {
            const halfW = widths[idxOf(call.from_class)] / 2;
            const rx = x1 + halfW - 4;
            return (
              <g key={i}>
                <path
                  d={`M${x1},${y - 6} C${rx + 22},${y - 14} ${rx + 22},${y + 8} ${x1},${y + 4}`}
                  fill="none" stroke="#4b5563" strokeWidth={1.5}
                />
                <polygon
                  points={`${x1},${y + 4} ${x1 + 7},${y} ${x1 - 1},${y - 1}`}
                  fill="#4b5563"
                />
                <text x={x1 + halfW + 6} y={y + 1}
                  fill="#9ca3af" fontSize={9} fontFamily="ui-monospace,monospace">
                  {label}
                </text>
              </g>
            );
          }

          const fwd = x2 > x1;
          const lineX2 = fwd ? x2 - 8 : x2 + 8;
          const mx = (x1 + x2) / 2;
          const arrowPts = fwd
            ? `${x2},${y} ${x2 - 9},${y - 4} ${x2 - 9},${y + 4}`
            : `${x2},${y} ${x2 + 9},${y - 4} ${x2 + 9},${y + 4}`;

          return (
            <g key={i}>
              <line x1={x1} y1={y} x2={lineX2} y2={y}
                stroke="#4b5563" strokeWidth={1.5} />
              <polygon points={arrowPts} fill="#4b5563" />
              <text x={mx} y={y - 6} textAnchor="middle"
                fill="#6b7280" fontSize={9} fontFamily="ui-monospace,monospace">
                {label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
