import { type InputHTMLAttributes, forwardRef, useId } from "react";

type InputSize = "sm" | "md";

interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  label?: string;
  error?: string;
  inputSize?: InputSize;
}

const sizeStyles: Record<InputSize, string> = {
  sm: "h-7 px-2 text-[var(--text-xs)]",
  md: "h-8 px-3 text-[var(--text-sm)]",
};

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, inputSize = "md", className = "", id: propId, ...props }, ref) => {
    const generatedId = useId();
    const id = propId ?? generatedId;

    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label
            htmlFor={id}
            className="text-[var(--text-xs)] font-medium text-[var(--color-text-secondary)]"
          >
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={id}
          className={[
            "rounded-[var(--radius-sm)] border bg-[var(--color-bg-secondary)]",
            "text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)]",
            "transition-colors duration-[var(--transition-fast)]",
            "focus:outline-none focus:border-[var(--color-accent)] focus:ring-1 focus:ring-[var(--color-accent)]",
            error
              ? "border-[var(--color-danger)]"
              : "border-[var(--color-border-default)]",
            sizeStyles[inputSize],
            className,
          ].join(" ")}
          {...props}
        />
        {error && (
          <span className="text-[var(--text-xs)] text-[var(--color-danger)]">
            {error}
          </span>
        )}
      </div>
    );
  }
);

Input.displayName = "Input";

export { Input, type InputProps, type InputSize };
