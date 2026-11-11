import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  "relative inline-flex shrink-0 select-none items-center justify-center gap-2 whitespace-nowrap rounded-full font-medium transition-[background-color,color,box-shadow,transform,border-color,filter] duration-300 ease-out active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-[1.1em] [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "bg-[linear-gradient(180deg,color-mix(in_oklab,var(--primary),white_14%),var(--primary))] text-primary-foreground shadow-[inset_0_1px_0_oklch(1_0_0/0.28),0_1px_2px_oklch(0.3_0.1_270/0.4),0_8px_20px_-8px_oklch(0.5_0.25_270/0.65)] hover:brightness-110 hover:shadow-[inset_0_1px_0_oklch(1_0_0/0.3),0_1px_2px_oklch(0.3_0.1_270/0.4),0_14px_28px_-8px_oklch(0.5_0.25_270/0.8)]",
        pix: "bg-[linear-gradient(180deg,color-mix(in_oklab,var(--pix),white_18%),var(--pix))] text-[oklch(0.2_0.06_165)] shadow-[inset_0_1px_0_oklch(1_0_0/0.4),0_8px_22px_-8px_oklch(0.7_0.17_165/0.7)] hover:brightness-105",
        secondary: "bg-surface-2 text-foreground hover:bg-primary-soft",
        outline:
          "border border-border-strong/70 bg-surface/80 text-foreground shadow-soft backdrop-blur hover:border-primary hover:text-primary",
        ghost: "text-foreground hover:bg-surface-2",
        danger: "bg-danger text-primary-foreground hover:brightness-110",
      },
      size: {
        sm: "h-9 px-3 text-sm",
        md: "h-11 px-6 text-[0.95rem]",
        lg: "h-14 px-8 text-base",
        icon: "size-11",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps extends ComponentProps<"button">, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export function Button({
  className,
  variant,
  size,
  asChild,
  type = "button",
  ...props
}: ButtonProps) {
  const Comp = asChild ? Slot.Root : "button";
  return (
    <Comp
      className={cn(buttonVariants({ variant, size }), className)}
      {...(asChild ? {} : { type })}
      {...props}
    />
  );
}
