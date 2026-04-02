interface SkeletonProps {
  width?: string;
  height?: string;
  rounded?: string;
  className?: string;
}

export function Skeleton({
  width,
  height = '1rem',
  rounded = 'rounded',
  className = '',
}: SkeletonProps) {
  return (
    <div
      className={`bg-raised animate-pulse ${rounded} ${className}`}
      style={{ width, height }}
      aria-hidden="true"
    />
  );
}
