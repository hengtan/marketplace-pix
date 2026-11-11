import type { CSSProperties } from "react";
import { useEffect } from "react";
import { Toaster as Sonner } from "sonner";
import { markToasterMounted } from "@/lib/toast";
import { useTheme } from "@/store/theme";

export default function Toaster() {
  const theme = useTheme((s) => s.theme);
  useEffect(markToasterMounted, []);
  return (
    <Sonner
      position="bottom-right"
      offset={{ right: 24, bottom: 92 }}
      mobileOffset={{ right: 16, bottom: 84 }}
      theme={theme}
      style={
        {
          "--normal-bg": "var(--glass)",
          "--normal-border": "var(--border-strong)",
          "--normal-text": "var(--foreground)",
          "--border-radius": "1.1rem",
        } as CSSProperties
      }
      toastOptions={{ className: "!backdrop-blur-xl !shadow-lift" }}
    />
  );
}
