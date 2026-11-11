import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  "inline-flex shrink-0 select-none items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium transition-[background-color,color,box-shadow,transform,border-color] duration-200 ease-out active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-[1.1em] [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "bg-primary text-primary-foreground shadow-soft hover:brightness-110 dark:hover:brightness-105",
        pix: "bg-pix text-[oklch(0.2_0.06_165)] shadow-soft hover:brightness-105",
        secondary: "bg-surface-2 text-foreground hover:bg-primary-soft",
        outline:
          "border border-border bg-surface text-foreground hover:border-primary hover:text-primary",
        ghost: "text-foreground hover:bg-surface-2",
        danger: "bg-danger text-primary-foreground hover:brightness-110",
      },
      size: {
        sm: "h-9 px-3 text-sm",
        md: "h-11 px-5 text-[0.95rem]",
        lg: "h-14 px-7 text-base",
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
