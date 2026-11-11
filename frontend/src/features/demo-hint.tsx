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
        Ambiente de desenvolvimento: lojistas criados pelo seed, como{" "}
        <span className="font-mono">trilha-sports@marketplace-pix.local</span>. A senha está em{" "}
        <span className="font-mono">IDENTITY_SEED_PASSWORD</span> no arquivo .env.
      </p>
    );
  }
  return null;
}
