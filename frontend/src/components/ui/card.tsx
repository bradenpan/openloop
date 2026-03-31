import { type HTMLAttributes, type ReactNode } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

interface CardHeaderProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

interface CardBodyProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

interface CardFooterProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

function Card({ className = "", children, ...props }: CardProps) {
  return (
    <div
      className={[
        "rounded-[var(--radius-md)] border border-[var(--color-border-default)]",
        "bg-[var(--color-bg-secondary)] shadow-[var(--shadow-subtle)]",
        className,
      ].join(" ")}
      {...props}
    >
      {children}
    </div>
  );
}

function CardHeader({ className = "", children, ...props }: CardHeaderProps) {
  return (
    <div
      className={[
        "px-4 py-3 border-b border-[var(--color-border-subtle)]",
        "text-[var(--text-sm)] font-semibold text-[var(--color-text-primary)]",
        className,
      ].join(" ")}
      {...props}
    >
      {children}
    </div>
  );
}

function CardBody({ className = "", children, ...props }: CardBodyProps) {
  return (
    <div
      className={["px-4 py-3", className].join(" ")}
      {...props}
    >
      {children}
    </div>
  );
}

function CardFooter({ className = "", children, ...props }: CardFooterProps) {
  return (
    <div
      className={[
        "px-4 py-3 border-t border-[var(--color-border-subtle)]",
        className,
      ].join(" ")}
      {...props}
    >
      {children}
    </div>
  );
}

export { Card, CardHeader, CardBody, CardFooter };
export type { CardProps, CardHeaderProps, CardBodyProps, CardFooterProps };
