import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { LayoutDashboard, LogOut, Package } from "lucide-react";
import { m } from "motion/react";
import { api } from "@/api/endpoints";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/misc";
import { signOut } from "@/features/session";
import { usePageTitle } from "@/hooks/utils";
import { EASE } from "@/lib/motion";
import { useAuth } from "@/store/auth";

const ROLE_LABEL: Record<string, string> = {
  customer: "Cliente",
  merchant: "Lojista",
  admin: "Administração",
};

export default function AccountPage() {
  usePageTitle("Minha conta");
  const navigate = useNavigate();
  const stored = useAuth((s) => s.user);
  const setUser = useAuth((s) => s.setUser);
  const me = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      const u = await api.me();
      setUser(u);
      return u;
    },
    staleTime: 60_000,
  });
  const user = me.data ?? stored;
  if (!user) return null;

  return (
    <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6 sm:py-16">
      <m.div
        initial={{ opacity: 0, y: 24, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.8, ease: EASE }}
        className="panel hairline-top relative overflow-hidden rounded-3xl p-8 sm:p-10"
      >
        <div className="aurora" aria-hidden>
          <i />
          <i />
          <i />
        </div>
        <span className="grid size-20 place-items-center rounded-3xl bg-[linear-gradient(135deg,var(--primary),oklch(0.62_0.22_320))] font-display text-3xl font-bold text-primary-foreground shadow-lift">
          {user.name.charAt(0).toUpperCase()}
        </span>
        <h1 className="mt-6 text-title">{user.name}</h1>
        <p className="mt-1 text-muted">{user.email}</p>
        <ul className="mt-5 flex flex-wrap gap-2" aria-label="Perfis de acesso">
          {user.roles.map((r) => (
            <li key={r}>
              <Badge tone={r === "merchant" ? "pix" : "primary"}>{ROLE_LABEL[r] ?? r}</Badge>
            </li>
          ))}
        </ul>
        <div className="mt-8 flex flex-wrap gap-3">
          <Button asChild variant="outline">
            <Link to="/pedidos">
              <Package /> Meus pedidos
            </Link>
          </Button>
          {user.roles.includes("merchant") && (
            <Button asChild>
              <Link to="/lojista">
                <LayoutDashboard /> Painel do lojista
              </Link>
            </Button>
          )}
          <Button
            variant="ghost"
            onClick={() => {
              void signOut();
              navigate({ to: "/" });
            }}
          >
            <LogOut /> Sair
          </Button>
        </div>
      </m.div>
    </div>
  );
}
