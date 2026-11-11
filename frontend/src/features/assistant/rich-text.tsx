import { Link } from "@tanstack/react-router";
import { Fragment, type ReactNode } from "react";
import type { Citation } from "./types";

type Block = { type: "p"; lines: string[] } | { type: "ul" | "ol"; items: string[] };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d{1,2}[.)]\s+(.*)$/;

export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let open: Block | null = null;

  const push = (type: Block["type"], value: string) => {
    if (open && open.type === type) {
      if (open.type === "p") open.lines.push(value);
      else open.items.push(value);
      return;
    }
    open = type === "p" ? { type, lines: [value] } : { type, items: [value] };
    blocks.push(open);
  };

  for (const raw of text.replace(/\r\n?/g, "\n").split("\n")) {
    if (raw.trim() === "") {
      open = null;
      continue;
    }
    const bullet = BULLET.exec(raw);
    const numbered = NUMBERED.exec(raw);
    if (bullet) push("ul", bullet[1] ?? "");
    else if (numbered) push("ol", numbered[1] ?? "");
    else push("p", raw.trim());
  }
  return blocks;
}

interface InlineProps {
  text: string;
  citations: Citation[];
  onNavigate?: () => void;
}

const INLINE = /\*\*([^*\n]+?)\*\*|\[(\d{1,2})\]|\*\*([^*\n]+)$/g;

function Inline({ text, citations, onNavigate }: InlineProps): ReactNode {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const match of text.matchAll(INLINE)) {
    const index = match.index ?? 0;
    if (index > last) out.push(text.slice(last, index));
    if (match[3] !== undefined) {
      out.push(
        <strong key={key++} className="font-semibold">
          {match[3]}
        </strong>,
      );
    } else if (match[1] !== undefined) {
      out.push(
        <strong key={key++} className="font-semibold">
          <Inline text={match[1]} citations={citations} onNavigate={onNavigate} />
        </strong>,
      );
    } else {
      const n = Number(match[2]);
      const citation = citations[n - 1];
      out.push(
        citation ? (
          <CitationChip key={key++} n={n} citation={citation} onNavigate={onNavigate} />
        ) : (
          match[0]
        ),
      );
    }
    last = index + match[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out.map((node, i) =>
    typeof node === "string" ? <Fragment key={`t${i}`}>{node}</Fragment> : node,
  );
}

export function CitationChip({
  n,
  citation,
  onNavigate,
}: {
  n: number;
  citation: Citation;
  onNavigate?: () => void;
}) {
  return (
    <Link
      to="/produto/$slug"
      params={{ slug: citation.slug }}
      onClick={onNavigate}
      aria-label={`Fonte ${n}: ${citation.name}`}
      title={citation.name}
      data-testid="citation-chip"
      className="mx-0.5 inline-grid h-[1.4rem] min-w-[1.4rem] -translate-y-px place-items-center rounded-full bg-primary-soft px-1 align-baseline text-[0.72rem] leading-none font-semibold text-primary tabular transition-colors hover:bg-primary hover:text-primary-foreground"
    >
      {n}
    </Link>
  );
}

function trimPartial(text: string): string {
  return text.replace(/(?:\[\d{0,2}|\*)$/, "");
}

function Caret() {
  return (
    <span
      aria-hidden
      className="ml-0.5 inline-block h-[1.05em] w-0.5 translate-y-0.5 animate-pulse rounded-full bg-primary"
    />
  );
}

interface RichTextProps {
  text: string;
  streaming?: boolean;
  citations?: Citation[];
  onNavigate?: () => void;
  className?: string;
}

export function RichText({
  text,
  streaming = false,
  citations = [],
  onNavigate,
  className,
}: RichTextProps) {
  const inline = (value: string) => (
    <Inline text={value} citations={citations} onNavigate={onNavigate} />
  );
  const blocks = parseBlocks(streaming ? trimPartial(text) : text);
  const lastBlock = blocks.length - 1;
  return (
    <div className={className}>
      {blocks.map((block, i) => {
        if (block.type === "p") {
          return (
            <p key={i} className="[&:not(:first-child)]:mt-3">
              {block.lines.map((line, j) => (
                <Fragment key={j}>
                  {j > 0 && <br />}
                  {inline(line)}
                  {streaming && i === lastBlock && j === block.lines.length - 1 && <Caret />}
                </Fragment>
              ))}
            </p>
          );
        }
        const List = block.type === "ul" ? "ul" : "ol";
        return (
          <List
            key={i}
            className={`grid gap-1.5 pl-5 [&:not(:first-child)]:mt-3 ${block.type === "ul" ? "list-disc marker:text-primary" : "list-decimal marker:font-semibold marker:text-primary"}`}
          >
            {block.items.map((item, j) => (
              <li key={j} className="pl-1">
                {inline(item)}
                {streaming && i === lastBlock && j === block.items.length - 1 && <Caret />}
              </li>
            ))}
          </List>
        );
      })}
    </div>
  );
}
