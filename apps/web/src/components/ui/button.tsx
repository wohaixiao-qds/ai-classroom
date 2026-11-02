import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-all outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground shadow-sm hover:bg-primary/90",
        secondary:
          "border border-border bg-secondary text-secondary-foreground hover:bg-accent hover:text-accent-foreground",
        outline: "border border-border bg-transparent hover:border-primary/50 hover:text-primary",
        ghost: "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
        destructive:
          "border border-destructive/30 bg-destructive/10 text-destructive hover:bg-destructive/20",
      },
      size: {
        default: "h-9 px-4",
        sm: "h-8 gap-1.5 px-3 text-xs",
        lg: "h-10 px-6",
        icon: "size-9",
        "icon-sm": "size-7 rounded-sm",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  }) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
