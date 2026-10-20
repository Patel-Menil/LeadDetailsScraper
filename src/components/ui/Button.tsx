import React from "react";
import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "outline" | "ghost" | "danger" | "success";
  size?: "sm" | "md" | "lg";
  isLoading?: boolean;
}

export function Button({
  children,
  variant = "primary",
  size = "md",
  isLoading = false,
  disabled,
  className,
  ...props
}: ButtonProps) {
  const variantStyles = {
    primary: "bg-blue-600 hover:bg-blue-500 text-white shadow-sm shadow-blue-500/20 border border-blue-500/40",
    secondary: "bg-slate-800 hover:bg-slate-700 text-slate-100 border border-slate-700",
    outline: "bg-transparent hover:bg-slate-800/60 text-slate-300 border border-slate-700 hover:text-white",
    ghost: "bg-transparent hover:bg-slate-800/50 text-slate-400 hover:text-slate-100 border-transparent",
    danger: "bg-rose-600/90 hover:bg-rose-500 text-white border border-rose-500/40",
    success: "bg-emerald-600 hover:bg-emerald-500 text-white border border-emerald-500/40",
  };

  const sizeStyles = {
    sm: "px-2.5 py-1.5 text-xs font-medium rounded-md",
    md: "px-4 py-2 text-sm font-medium rounded-lg",
    lg: "px-5 py-2.5 text-base font-semibold rounded-lg",
  };

  return (
    <button
      disabled={disabled || isLoading}
      className={cn(
        "inline-flex items-center justify-center gap-2 transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:ring-offset-2 focus:ring-offset-[#0a0d14] disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer",
        variantStyles[variant],
        sizeStyles[size],
        className
      )}
      {...props}
    >
      {isLoading && <Loader2 className="w-4 h-4 animate-spin text-current" />}
      {children}
    </button>
  );
}
