import { Armchair, Cpu, Mountain, Package } from "lucide-react";
import { type CSSProperties, useState } from "react";
import { cn } from "@/lib/utils";

const CATEGORY_HUE: Record<string, number> = { tecnologia: 268, casa: 55, esporte: 165 };

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

function Glyph({ category, className }: { category: string; className?: string }) {
  if (category === "tecnologia") return <Cpu className={className} strokeWidth={1.25} />;
  if (category === "casa") return <Armchair className={className} strokeWidth={1.25} />;
  if (category === "esporte") return <Mountain className={className} strokeWidth={1.25} />;
  return <Package className={className} strokeWidth={1.25} />;
}

interface Props {
  src: string | null;
  alt: string;
  category: string;
  seed: string;
  className?: string;
  glyphClassName?: string;
  priority?: boolean;
  size?: number;
}

export function ProductImage({
  src,
  alt,
  category,
  seed,
  className,
  glyphClassName,
  priority,
  size = 640,
}: Props) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const showImage = src && !failed;
  const h = hash(seed);
  const hue = (CATEGORY_HUE[category] ?? 268) + (h % 40) - 20;
  const style = {
    "--h": hue,
    backgroundImage: `radial-gradient(120% 90% at ${20 + (h % 60)}% 0%, oklch(0.9 0.09 var(--h)), transparent 60%), linear-gradient(155deg, oklch(0.84 0.1 var(--h)), oklch(0.6 0.16 calc(var(--h) + 24)))`,
  } as CSSProperties;

  return (
    <div
      className={cn("relative aspect-square overflow-hidden bg-surface-2", className)}
      style={showImage && loaded ? undefined : style}
    >
      {showImage ? (
        <img
          src={src}
          alt={alt}
          width={size}
          height={size}
          loading={priority ? "eager" : "lazy"}
          decoding="async"
          fetchPriority={priority ? "high" : "auto"}
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
          className={cn(
            "absolute inset-0 size-full object-cover transition-opacity duration-500",
            loaded ? "opacity-100" : "opacity-0",
          )}
        />
      ) : (
        <div
          {...(alt ? { role: "img", "aria-label": alt } : { "aria-hidden": true })}
          className="absolute inset-0 grid place-items-center"
        >
          <Glyph
            category={category}
            className={cn("size-1/3 text-white/85 drop-shadow-sm", glyphClassName)}
          />
        </div>
      )}
    </div>
  );
}
