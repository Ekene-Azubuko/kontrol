import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
/** Merge utility classes using the shared shadcn convention. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
/** Render UTC-backed API dates in the user's local time. */
export function time(value?: string | null) {
  return value
    ? new Date(
        value.endsWith("Z") || /[+-]\d\d:\d\d$/.test(value)
          ? value
          : `${value}Z`,
      ).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "—";
}
