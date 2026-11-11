import { env } from "@/lib/env";

const box = "rounded-xl bg-surface-2 px-4 py-3 text-xs text-muted";

export function DemoHint() {
  if (env.useMocks) {
    return (
      <p className={box}>
        Conta de demonstração: <span className="font-mono">lojista@praca.dev</span> com a senha{" "}
        <span className="font-mono">praca1234</span>.
      </p>
    );
  }
  if (env.devTools) {
    return (
      <p className={box}>
        Ambiente de desenvolvimento: lojistas do seed, como{" "}
        <span className="font-mono">trilha-sports@marketplace-pix.local</span>, com a senha{" "}
        <span className="font-mono">praca1234</span>.
      </p>
    );
  }
  return null;
}
