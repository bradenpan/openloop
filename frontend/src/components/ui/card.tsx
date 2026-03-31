import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
  className?: string;
}

export function Card({ children, className = '' }: Props) {
  return (
    <div className={`bg-surface border border-border rounded-lg ${className}`}>
      {children}
    </div>
  );
}

export function CardHeader({ children, className = '' }: Props) {
  return (
    <div className={`px-4 py-3 border-b border-border ${className}`}>
      {children}
    </div>
  );
}

export function CardBody({ children, className = '' }: Props) {
  return <div className={`px-4 py-3 ${className}`}>{children}</div>;
}

export function CardFooter({ children, className = '' }: Props) {
  return (
    <div className={`px-4 py-3 border-t border-border ${className}`}>
      {children}
    </div>
  );
}
