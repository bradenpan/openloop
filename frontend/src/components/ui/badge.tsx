import { type HTMLAttributes } from "react";

type BadgeVariant = "default" | "success" | "warning" | "danger" | "info";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

const variantStyles: Record<BadgeVariant, string> = {
  default:
    "bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)]",
  success:
    "bg-[var(--color-success-muted)] text-[var(--color-success)]",
  warning:
    "bg-[var(--color-warning-muted)] text-[var(--color-warning)]",
  danger:
    "bg-[var(--color-danger-muted)] text-[var(--color-danger)]",
  info:
    "bg-[var(--color-info-muted)] text-[var(--color-info)]",
};

function Badge({ variant = "default", className = "", children, ...props }: BadgeProps) {
  return (
    <span
      className={[
        "inline-flex items-center px-1.5 py-0.5",
        "text-[var(--text-xs)] font-medium leading-none",
        "rounded-[var(--radius-sm)]",
        variantStyles[variant],
        className,
      ].join(" ")}
      {...props}
    >
      {children}
    </span>
  );
}

export { Badge, type BadgeProps, type BadgeVariant };
