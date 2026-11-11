import { Link, useNavigate } from "@tanstack/react-router";
import { LayoutDashboard, LogIn, LogOut, UserRound } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/store/auth";

function initials(name: string): string {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p.charAt(0).toUpperCase())
    .join("");
}

const item =
  "flex h-11 cursor-pointer items-center gap-3 rounded-lg px-3 text-sm outline-none data-[highlighted]:bg-primary-soft data-[highlighted]:text-primary";

export function UserMenu() {
  const user = useAuth((s) => s.user);
  const clear = useAuth((s) => s.clear);
  const navigate = useNavigate();

  if (!user) {
    return (
      <>
        <Button asChild variant="ghost" size="sm" className="hidden sm:inline-flex">
          <Link to="/entrar">
            <LogIn /> Entrar
          </Link>
        </Button>
        <Link
          to="/entrar"
          aria-label="Entrar"
          className="grid size-11 place-items-center rounded-full hover:bg-surface-2 sm:hidden"
        >
          <UserRound className="size-5" />
        </Link>
      </>
    );
  }

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          aria-label={`Conta de ${user.name}`}
          className="grid size-11 place-items-center rounded-full"
        >
          <span
            aria-hidden
            data-initials={initials(user.name)}
            className="grid size-9 place-items-center rounded-full bg-[linear-gradient(135deg,var(--primary),oklch(0.62_0.22_320))] text-xs font-bold text-primary-foreground shadow-soft after:content-[attr(data-initials)]"
          />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className="glass z-[70] w-64 rounded-2xl p-1.5 shadow-lift data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=open]:slide-in-from-top-2"
        >
          <div className="px-3 py-2.5">
            <p className="truncate font-semibold">{user.name}</p>
            <p className="truncate text-sm text-muted">{user.email}</p>
          </div>
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Item asChild className={item}>
            <Link to="/conta">
              <UserRound className="size-4" /> Minha conta
            </Link>
          </DropdownMenu.Item>
          {user.roles.includes("merchant") && (
            <DropdownMenu.Item asChild className={item}>
              <Link to="/lojista">
                <LayoutDashboard className="size-4" /> Painel do lojista
              </Link>
            </DropdownMenu.Item>
          )}
          <DropdownMenu.Item
            className={item}
            onSelect={() => {
              clear();
              toast.success("Você saiu da conta");
              navigate({ to: "/" });
            }}
          >
            <LogOut className="size-4" /> Sair
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
