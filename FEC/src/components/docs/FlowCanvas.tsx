import { useTranslation } from "react-i18next";

/**
 * The pipeline drawn as a node graph, in the shape people recognise from
 * n8n: trigger on the left, one node per step, branches that rejoin.
 * Hand-laid on an SVG grid rather than a library — it must render inside the
 * client's page with no external dependency and stay legible on a phone.
 */

type NodeKind = "trigger" | "source" | "step" | "decision" | "store" | "output";

interface FlowNode {
  id: string;
  x: number;
  y: number;
  icon: string;
  title: string;
  sub?: string;
  kind: NodeKind;
}

const W = 176;
const H = 62;

const KIND_STYLE: Record<NodeKind, { fill: string; stroke: string; text: string }> = {
  trigger: { fill: "#FFFFFF", stroke: "#C93B42", text: "#C93B42" },
  source: { fill: "#EEF5FD", stroke: "#D5E3F2", text: "#2C4984" },
  step: { fill: "#FFFFFF", stroke: "#4A6FAC", text: "#2C4984" },
  decision: { fill: "#FFFFFF", stroke: "#B7791F", text: "#B7791F" },
  store: { fill: "#EEF5FD", stroke: "#4A6FAC", text: "#2C4984" },
  output: { fill: "#FFFFFF", stroke: "#1E7E4A", text: "#1E7E4A" },
};

export function FlowCanvas() {
  const { t } = useTranslation();

  const nodes: FlowNode[] = [
    { id: "cron", x: 20, y: 150, icon: "⏰", kind: "trigger", title: t("flow.cron"), sub: t("flow.cronSub") },
    { id: "ig", x: 240, y: 60, icon: "📸", kind: "source", title: t("flow.ig"), sub: t("flow.igSub") },
    { id: "blog", x: 240, y: 240, icon: "📄", kind: "source", title: t("flow.blog"), sub: t("flow.blogSub") },
    { id: "dl", x: 460, y: 60, icon: "⬇️", kind: "step", title: t("flow.download"), sub: t("flow.downloadSub") },
    { id: "stt", x: 680, y: 60, icon: "🎧", kind: "step", title: t("flow.stt"), sub: t("flow.sttSub") },
    { id: "gate", x: 900, y: 60, icon: "🚦", kind: "decision", title: t("flow.gate"), sub: t("flow.gateSub") },
    { id: "llm", x: 1120, y: 60, icon: "🧠", kind: "step", title: t("flow.llm"), sub: t("flow.llmSub") },
    { id: "skip", x: 1120, y: 168, icon: "⛔", kind: "decision", title: t("flow.skip"), sub: t("flow.skipSub") },
    { id: "emb", x: 900, y: 240, icon: "🔢", kind: "step", title: t("flow.embed"), sub: t("flow.embedSub") },
    { id: "cluster", x: 680, y: 240, icon: "🧭", kind: "step", title: t("flow.cluster"), sub: t("flow.clusterSub") },
    { id: "topics", x: 460, y: 240, icon: "👤", kind: "step", title: t("flow.topics"), sub: t("flow.topicsSub") },
    { id: "db", x: 240, y: 360, icon: "🗄️", kind: "store", title: t("flow.db"), sub: t("flow.dbSub") },
    { id: "brain", x: 680, y: 360, icon: "💡", kind: "output", title: t("flow.brain"), sub: t("flow.brainSub") },
    { id: "ui", x: 1120, y: 360, icon: "🖥️", kind: "output", title: t("flow.ui"), sub: t("flow.uiSub") },
  ];

  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));

  const edges: [string, string, string?][] = [
    ["cron", "ig"], ["cron", "blog"],
    ["ig", "dl"], ["dl", "stt"], ["stt", "gate"],
    ["gate", "llm", t("flow.hasContent")],
    ["gate", "skip", t("flow.noContent")],
    ["llm", "emb"], ["blog", "emb"],
    ["emb", "cluster"], ["cluster", "topics"],
    ["topics", "db"], ["cluster", "brain"], ["brain", "ui"], ["db", "brain"],
  ];

  /** Orthogonal connector: out of the right edge, into the left edge. */
  const path = (a: FlowNode, b: FlowNode) => {
    const x1 = a.x + W, y1 = a.y + H / 2;
    const x2 = b.x, y2 = b.y + H / 2;
    if (b.x < a.x) {
      // going back leftwards: drop below both, then travel
      const midY = Math.max(y1, y2) + 58;
      return `M${x1} ${y1} H${x1 + 26} V${midY} H${x2 - 26} V${y2} H${x2}`;
    }
    const midX = (x1 + x2) / 2;
    return `M${x1} ${y1} H${midX} V${y2} H${x2}`;
  };

  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-white p-3 shadow-card">
      <svg viewBox="0 0 1340 470" className="h-auto w-full min-w-[900px]" role="img"
           aria-label={t("flow.aria")}>
        <defs>
          <marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto">
            <path d="M0,0 L9,4.5 L0,9 z" fill="#9DB4D6" />
          </marker>
          <pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">
            <circle cx="1.5" cy="1.5" r="1.1" fill="#D5E3F2" />
          </pattern>
        </defs>
        <rect width="1340" height="470" fill="url(#dots)" rx="10" />

        {edges.map(([from, to, label], i) => {
          const a = byId[from], b = byId[to];
          const d = path(a, b);
          return (
            <g key={i}>
              <path d={d} fill="none" stroke="#9DB4D6" strokeWidth="1.6" markerEnd="url(#arrow)" />
              {label && (
                <text x={(a.x + W + b.x) / 2} y={(a.y + b.y) / 2 + H / 2 - 8}
                      fontSize="11" fill="#52688A" textAnchor="middle" fontWeight="600">
                  {label}
                </text>
              )}
            </g>
          );
        })}

        {nodes.map((n) => {
          const st = KIND_STYLE[n.kind];
          return (
            <g key={n.id}>
              <rect x={n.x} y={n.y} width={W} height={H} rx="12"
                    fill={st.fill} stroke={st.stroke} strokeWidth="1.6" />
              <text x={n.x + 14} y={n.y + 26} fontSize="16">{n.icon}</text>
              <text x={n.x + 38} y={n.y + 26} fontSize="12.5" fontWeight="700" fill={st.text}>
                {n.title}
              </text>
              {n.sub && (
                <text x={n.x + 14} y={n.y + 46} fontSize="10.5" fill="#52688A">
                  {n.sub}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
