import { Link } from "@tanstack/react-router";
import { LogIn, UserRound } from "lucide-react";
import { type ComponentProps, Suspense, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { lazyReload } from "@/lib/lazy-reload";
import { useAuth } from "@/store/auth";

const UserDropdown = lazyReload(() => import("./user-dropdown"));

function initials(name: string): string {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p.charAt(0).toUpperCase())
    .join("");
}

function Avatar({
  name,
  onActivate,
  ...rest
}: { name: string; onActivate?: () => void } & ComponentProps<"button">) {
  return (
    <button
      type="button"
      aria-label={`Conta de ${name}`}
      {...rest}
      onClick={(e) => {
        rest.onClick?.(e);
        onActivate?.();
      }}
      className="grid size-11 place-items-center rounded-full"
    >
      <span
        aria-hidden
        data-initials={initials(name)}
        className="grid size-9 place-items-center rounded-full bg-[linear-gradient(135deg,var(--primary),oklch(0.62_0.22_320))] text-xs font-bold text-primary-foreground shadow-soft after:content-[attr(data-initials)]"
      />
    </button>
  );
}

export function UserMenu() {
  const user = useAuth((s) => s.user);
  const restoring = useAuth((s) => s.restoring);
  const [armed, setArmed] = useState(false);
  const [opened, setOpened] = useState(false);

  useEffect(() => {
    if (!user) return;
    const id = (window.requestIdleCallback ?? ((cb: () => void) => setTimeout(cb, 3000)))(
      () => void import("./user-dropdown"),
    );
    return () => window.cancelIdleCallback?.(id as number);
  }, [user]);

  if (restoring && !user) return <span aria-hidden className="size-11" />;

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

  const plain = (
    <Avatar
      name={user.name}
      onActivate={() => {
        setOpened(true);
        setArmed(true);
      }}
    />
  );
  if (!armed) return plain;
  return (
    <Suspense fallback={plain}>
      <UserDropdown
        name={user.name}
        email={user.email}
        merchant={user.roles.includes("merchant")}
        defaultOpen={opened}
        trigger={<Avatar name={user.name} />}
      />
    </Suspense>
  );
}
