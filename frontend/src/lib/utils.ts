import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatINR(value: number, showSign = false): string {
  const absVal = Math.abs(value);
  const formatted = absVal.toLocaleString("en-IN", {
    maximumFractionDigits: 0,
  });
  if (showSign) {
    return `${value >= 0 ? "+₹" : "-₹"}${formatted}`;
  }
  return `${value < 0 ? "-₹" : "₹"}${formatted}`;
}
