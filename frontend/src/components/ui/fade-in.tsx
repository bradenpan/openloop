import { useEffect, useState, type ReactNode } from 'react';

interface FadeInProps {
  children: ReactNode;
  duration?: number;
  className?: string;
}

export function FadeIn({ children, duration = 150, className = '' }: FadeInProps) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    requestAnimationFrame(() => setVisible(true));
  }, []);

  return (
    <div
      className={`transition-opacity ease-out ${visible ? 'opacity-100' : 'opacity-0'} ${className}`}
      style={{ transitionDuration: `${duration}ms` }}
    >
      {children}
    </div>
  );
}
