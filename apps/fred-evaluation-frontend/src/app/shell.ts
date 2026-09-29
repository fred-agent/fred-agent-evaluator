import { createContext, useContext } from "react";

/** The themed `.fred-ui` root: dialogs portal into it so they keep the theme. */
export const ShellContext = createContext<HTMLElement | null>(null);

export function useShellElement(): HTMLElement | null {
  return useContext(ShellContext);
}
