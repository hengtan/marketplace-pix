import { type CSSProperties, useState } from "react";
import { cn } from "@/lib/utils";
import { hashOf, kindFor, ProductArt } from "./product-art";

const CATEGORY_HUE: Record<string, number> = { tecnologia: 272, casa: 48, esporte: 168 };

function firstParty(src: string | null): src is string {
  if (!src) return false;
  return src.startsWith("/") && !src.startsWith("//");
}

interface Props {
  src: string | null;
  alt: string;
  category: string;
  seed: string;
  className?: string;
  priority?: boolean;
  size?: number;
  float?: boolean;
}

export function artStyle(category: string, seed: string): CSSProperties {
  const h = hashOf(seed);
  const hue = (CATEGORY_HUE[category] ?? 272) + (h % 36) - 18;
  return {
    "--art-bg1": `oklch(var(--art-l1) 0.1 ${hue})`,
    "--art-bg2": `oklch(var(--art-l2) 0.19 ${hue + 28})`,
    "--art-hi": "oklch(0.985 0.01 90)",
    "--art-mid": `oklch(0.86 0.06 ${hue})`,
    "--art-lo": `oklch(0.3 0.09 ${hue + 10})`,
    "--art-acc": `oklch(0.78 0.17 ${(hue + 150) % 360})`,
  } as CSSProperties;
}

export function ProductImage({
  src,
  alt,
  category,
  seed,
  className,
  priority,
  size = 640,
  float,
}: Props) {
  const [failed, setFailed] = useState(false);
  const useImage = firstParty(src) && !failed;
  const h = hashOf(seed);

  return (
    <div
      className={cn("relative aspect-square overflow-hidden bg-surface-2", className)}
      style={artStyle(category, seed)}
    >
      {useImage ? (
        <img
          src={src}
          alt={alt}
          width={size}
          height={size}
          loading={priority ? "eager" : "lazy"}
          decoding="async"
          onError={() => setFailed(true)}
          className="absolute inset-0 size-full object-cover"
        />
      ) : (
        <div
          {...(alt ? { role: "img", "aria-label": alt } : { "aria-hidden": true })}
          className="absolute inset-0"
        >
          <ProductArt kind={kindFor(seed, category)} seed={h} float={float} />
        </div>
      )}
    </div>
  );
}
