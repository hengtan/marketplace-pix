import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

process.env.VITE_API_URL ??= "http://localhost:8000";
process.env.VITE_USE_MOCKS ??= "false";

const HOME_FONTS =
  /(geist-latin-wght|bricolage-grotesque-wdth90-latin|instrument-serif-latin-400-italic)[^/]*\.woff2$/;

function homeFontPreload(): Plugin {
  return {
    name: "home-font-preload",
    transformIndexHtml: {
      order: "post",
      handler(html, ctx) {
        if (!ctx.bundle) return html;
        const urls = Object.values(ctx.bundle)
          .filter((f) => f.type === "asset" && HOME_FONTS.test(f.fileName))
          .map((f) => `/${f.fileName}`);
        const script = `<script>if(location.pathname==="/"){${JSON.stringify(urls)}.forEach(function(h){var l=document.createElement("link");l.rel="preload";l.as="font";l.type="font/woff2";l.crossOrigin="";l.href=h;document.head.appendChild(l)})}</script>`;
        return html.replace("</title>", `</title>\n    ${script}`);
      },
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), homeFontPreload()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
  server: {
    port: 5173,
    strictPort: true,
    proxy: process.env.VITE_PROXY_TARGET
      ? { "/api": { target: process.env.VITE_PROXY_TARGET, changeOrigin: true } }
      : undefined,
  },
  preview: {
    proxy: process.env.VITE_PROXY_TARGET
      ? { "/api": { target: process.env.VITE_PROXY_TARGET, changeOrigin: true } }
      : undefined,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
