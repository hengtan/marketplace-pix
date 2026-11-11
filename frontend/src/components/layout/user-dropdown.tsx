import { Link, useNavigate } from "@tanstack/react-router";
import { LayoutDashboard, LogOut, UserRound } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import { signOut } from "@/features/session";
import { toast } from "@/lib/toast";

const item =
  "flex h-11 cursor-pointer items-center gap-3 rounded-lg px-3 text-sm outline-none data-[highlighted]:bg-primary-soft data-[highlighted]:text-primary";

export default function UserDropdown({
  name,
  email,
  merchant,
  defaultOpen,
  trigger,
}: {
  name: string;
  email: string;
  merchant: boolean;
  defaultOpen: boolean;
  trigger: React.ReactNode;
}) {
  const navigate = useNavigate();

  return (
    <DropdownMenu.Root defaultOpen={defaultOpen}>
      <DropdownMenu.Trigger asChild>{trigger}</DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className="glass z-[70] w-64 rounded-2xl p-1.5 shadow-lift data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=open]:slide-in-from-top-2"
        >
          <div className="px-3 py-2.5">
            <p className="truncate font-semibold">{name}</p>
            <p className="truncate text-sm text-muted">{email}</p>
          </div>
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Item asChild className={item}>
            <Link to="/conta">
              <UserRound className="size-4" /> Minha conta
            </Link>
          </DropdownMenu.Item>
          {merchant && (
            <DropdownMenu.Item asChild className={item}>
              <Link to="/lojista">
                <LayoutDashboard className="size-4" /> Painel do lojista
              </Link>
            </DropdownMenu.Item>
          )}
          <DropdownMenu.Item
            className={item}
            onSelect={() => {
              void signOut();
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
