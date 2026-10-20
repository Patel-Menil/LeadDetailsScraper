import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDateTime(isoString?: string) {
  if (!isoString) return "—";
  try {
    return new Date(isoString).toLocaleString();
  } catch {
    return isoString;
  }
}

export function formatDate(isoString?: string) {
  if (!isoString) return "—";
  try {
    return new Date(isoString).toLocaleDateString();
  } catch {
    return isoString;
  }
}
