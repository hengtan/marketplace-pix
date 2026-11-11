import type { CSSProperties, ReactNode } from "react";

export type ArtKind =
  | "headphones"
  | "speaker"
  | "watch"
  | "keyboard"
  | "gadget"
  | "lamp"
  | "vessel"
  | "fabric"
  | "bag"
  | "shoe"
  | "helmet"
  | "loop"
  | "blades"
  | "clock";

const KEYWORDS: [RegExp, ArtKind][] = [
  [/fone|headphone/, "headphones"],
  [/caixa|som|speaker|difusor/, "speaker"],
  [/parede|minimal/, "clock"],
  [/relogio|smartwatch|watch|gps/, "watch"],
  [/teclado|keyboard/, "keyboard"],
  [/luminaria|lamp/, "lamp"],
  [/cafeteira|vaso|garrafa|termica/, "vessel"],
  [/manta|tapete|yoga/, "fabric"],
  [/mochila|organizador|bambu/, "bag"],
  [/tenis|corrida/, "shoe"],
  [/capacete|helmet/, "helmet"],
  [/corda|elastico|kit/, "loop"],
  [/faca|chef/, "blades"],
];

export function kindFor(seed: string, category: string): ArtKind {
  for (const [re, kind] of KEYWORDS) if (re.test(seed)) return kind;
  if (category === "casa") return "vessel";
  if (category === "esporte") return "loop";
  return "gadget";
}

export function hashOf(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

const HI = { fill: "var(--art-hi)" } as CSSProperties;
const MID = { fill: "var(--art-mid)" } as CSSProperties;
const LO = { fill: "var(--art-lo)" } as CSSProperties;
const ACC = { fill: "var(--art-acc)" } as CSSProperties;
const strokeLo = { stroke: "var(--art-lo)", fill: "none" } as CSSProperties;
const strokeAcc = { stroke: "var(--art-acc)", fill: "none" } as CSSProperties;
const strokeHi = { stroke: "var(--art-hi)", fill: "none" } as CSSProperties;

function Shine({ x, y, w, h, r = 4 }: { x: number; y: number; w: number; h: number; r?: number }) {
  return <rect x={x} y={y} width={w} height={h} rx={r} fill="white" opacity={0.38} />;
}

const OBJECTS: Record<ArtKind, () => ReactNode> = {
  headphones: () => (
    <>
      <path d="M54 118a46 46 0 0 1 92 0" strokeWidth="9" strokeLinecap="round" style={strokeLo} />
      <rect x="42" y="108" width="26" height="44" rx="12" style={HI} />
      <rect x="132" y="108" width="26" height="44" rx="12" style={HI} />
      <rect x="62" y="116" width="10" height="28" rx="5" style={ACC} />
      <rect x="128" y="116" width="10" height="28" rx="5" style={ACC} />
      <Shine x={46} y={113} w={5} h={26} />
    </>
  ),
  speaker: () => (
    <>
      <rect x="62" y="56" width="76" height="92" rx="36" style={HI} />
      <ellipse cx="100" cy="68" rx="24" ry="6" style={MID} />
      {[0, 1, 2, 3].map((r) =>
        [0, 1, 2].map((c) => (
          <circle
            key={`${r}-${c}`}
            cx={82 + c * 18}
            cy={88 + r * 14}
            r="3.2"
            style={LO}
            opacity={0.55}
          />
        )),
      )}
      <circle cx="100" cy="136" r="5" style={ACC} />
      <Shine x={68} y={78} w={5} h={48} />
    </>
  ),
  watch: () => (
    <>
      <rect x="82" y="34" width="36" height="132" rx="14" style={LO} opacity={0.85} />
      <rect x="64" y="64" width="72" height="72" rx="24" style={HI} />
      <rect x="136" y="92" width="6" height="16" rx="3" style={MID} />
      <circle cx="100" cy="100" r="25" style={LO} />
      <path d="M100 100V84M100 100l12 8" strokeWidth="4" strokeLinecap="round" style={strokeAcc} />
      <circle cx="100" cy="100" r="3" style={ACC} />
    </>
  ),
  keyboard: () => (
    <>
      <rect x="30" y="76" width="140" height="68" rx="12" style={HI} />
      {[0, 1, 2].map((r) =>
        Array.from({ length: 9 }, (_, c) => (
          <rect
            key={`${r}-${c}`}
            x={39 + c * 14}
            y={85 + r * 15}
            width="11"
            height="11"
            rx="3"
            style={c === 8 && r === 0 ? ACC : MID}
          />
        )),
      )}
      <rect x="56" y="130" width="88" height="8" rx="4" style={MID} />
    </>
  ),
  gadget: () => (
    <>
      <rect x="62" y="64" width="76" height="76" rx="22" style={HI} />
      <circle cx="100" cy="96" r="24" style={LO} />
      <circle cx="100" cy="96" r="13" style={MID} />
      <circle cx="94" cy="90" r="4" fill="white" opacity={0.7} />
      <rect x="84" y="126" width="32" height="6" rx="3" style={ACC} />
    </>
  ),
  lamp: () => (
    <>
      <circle cx="140" cy="88" r="38" style={ACC} opacity={0.22} />
      <path d="M66 152h56" strokeWidth="9" strokeLinecap="round" style={strokeLo} />
      <path d="M94 152V76q0-30 40-30" strokeWidth="6" strokeLinecap="round" style={strokeLo} />
      <path d="M122 42h30l-8 30h-14z" style={ACC} />
      <circle cx="137" cy="76" r="5" fill="white" opacity={0.85} />
    </>
  ),
  vessel: () => (
    <>
      <rect x="86" y="42" width="28" height="24" rx="8" style={MID} />
      <rect x="68" y="62" width="64" height="94" rx="28" style={HI} />
      <rect x="68" y="96" width="64" height="18" style={ACC} opacity={0.85} />
      <Shine x={77} y={72} w={7} h={56} />
    </>
  ),
  fabric: () => (
    <>
      <rect x="40" y="108" width="120" height="38" rx="14" style={LO} opacity={0.8} />
      <rect x="46" y="88" width="108" height="38" rx="14" style={MID} />
      <rect x="52" y="68" width="96" height="38" rx="14" style={HI} />
      {[0, 1, 2].map((i) => (
        <rect key={i} x={72 + i * 22} y="68" width="6" height="38" style={ACC} opacity={0.5} />
      ))}
    </>
  ),
  bag: () => (
    <>
      <path d="M80 62q0-18 20-18t20 18" strokeWidth="7" strokeLinecap="round" style={strokeLo} />
      <rect x="60" y="56" width="80" height="102" rx="30" style={HI} />
      <rect x="74" y="108" width="52" height="38" rx="14" style={MID} />
      <path d="M80 92h40" strokeWidth="5" strokeLinecap="round" style={strokeAcc} />
      <Shine x={67} y={70} w={6} h={30} />
    </>
  ),
  shoe: () => (
    <>
      <path
        d="M38 132q0-34 28-38l22-28q10 14 32 22 28 6 38 24v20q0 8-8 8H46q-8 0-8-8z"
        style={HI}
      />
      <rect x="36" y="138" width="130" height="14" rx="7" style={ACC} />
      <path
        d="M92 80l10 10M80 92l12 10M104 94l10 8"
        strokeWidth="4"
        strokeLinecap="round"
        style={strokeLo}
        opacity={0.6}
      />
      <path
        d="M118 112q22 4 40 16"
        strokeWidth="5"
        strokeLinecap="round"
        style={strokeAcc}
        opacity={0.9}
      />
    </>
  ),
  helmet: () => (
    <>
      <path d="M40 124a60 60 0 0 1 120 0z" style={HI} />
      {[0, 1, 2].map((i) => (
        <rect
          key={i}
          x={66 + i * 24}
          y="76"
          width="12"
          height="30"
          rx="6"
          style={LO}
          opacity={0.5}
        />
      ))}
      <rect x="36" y="122" width="128" height="14" rx="7" style={ACC} />
      <path d="M72 136q4 22 28 22t28-22" strokeWidth="5" strokeLinecap="round" style={strokeLo} />
    </>
  ),
  loop: () => (
    <>
      <circle cx="100" cy="100" r="46" strokeWidth="9" style={strokeHi} />
      <circle cx="100" cy="100" r="30" strokeWidth="7" style={strokeAcc} />
      <rect x="40" y="86" width="22" height="28" rx="10" style={LO} />
      <rect x="138" y="86" width="22" height="28" rx="10" style={LO} />
    </>
  ),
  blades: () => (
    <>
      <rect x="66" y="48" width="14" height="52" rx="5" style={LO} />
      <rect x="90" y="40" width="14" height="60" rx="5" style={MID} />
      <rect x="114" y="52" width="14" height="48" rx="5" style={LO} />
      <rect x="54" y="92" width="92" height="64" rx="12" style={HI} />
      <rect x="54" y="92" width="92" height="12" rx="6" style={ACC} />
    </>
  ),
  clock: () => (
    <>
      <circle cx="100" cy="100" r="52" style={HI} />
      <circle cx="100" cy="100" r="44" style={MID} opacity={0.55} />
      {Array.from({ length: 12 }, (_, i) => (
        <rect
          key={i}
          x="98.5"
          y="60"
          width="3"
          height={i % 3 === 0 ? 10 : 5}
          rx="1.5"
          style={LO}
          transform={`rotate(${i * 30} 100 100)`}
        />
      ))}
      <path d="M100 100V76M100 100l16 10" strokeWidth="4" strokeLinecap="round" style={strokeAcc} />
      <circle cx="100" cy="100" r="4" style={ACC} />
    </>
  ),
};

export function ProductArt({
  kind,
  seed,
  float = false,
}: {
  kind: ArtKind;
  seed: number;
  float?: boolean;
}) {
  const ox = 20 + (seed % 60);
  const oy = 14 + ((seed >> 3) % 50);
  const rings = 2 + (seed % 2);
  const id = `art-${seed}-${kind}`;
  return (
    <svg
      viewBox="0 0 200 200"
      className="absolute inset-0 size-full"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden
      focusable="false"
    >
      <defs>
        <linearGradient id={`${id}-bg`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" style={{ stopColor: "var(--art-bg1)" }} />
          <stop offset="1" style={{ stopColor: "var(--art-bg2)" }} />
        </linearGradient>
        <radialGradient id={`${id}-glow`} cx="50%" cy="50%" r="50%">
          <stop offset="0" stopColor="white" stopOpacity="0.55" />
          <stop offset="1" stopColor="white" stopOpacity="0" />
        </radialGradient>
        <pattern id={`${id}-dots`} width="14" height="14" patternUnits="userSpaceOnUse">
          <circle cx="2" cy="2" r="1.1" fill="white" opacity="0.22" />
        </pattern>
      </defs>
      <rect width="200" height="200" fill={`url(#${id}-bg)`} />
      <rect width="200" height="200" fill={`url(#${id}-dots)`} />
      <circle cx={ox + 40} cy={oy + 30} r="86" fill={`url(#${id}-glow)`} />
      {Array.from({ length: rings }, (_, i) => (
        <circle
          key={i}
          cx="100"
          cy="104"
          r={56 + i * 22}
          fill="none"
          stroke="white"
          strokeOpacity={0.16 - i * 0.04}
          strokeWidth="1.2"
        />
      ))}
      <ellipse cx="100" cy="162" rx="50" ry="8" fill="black" opacity="0.22" />
      <g className={float ? "[animation:float_6s_ease-in-out_infinite]" : undefined}>
        {OBJECTS[kind]()}
      </g>
    </svg>
  );
}
