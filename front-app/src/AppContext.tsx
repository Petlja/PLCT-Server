import { createContext } from "react";

export interface AppContextType {
    accessKey: string | null;
}

export const AppContext = createContext<AppContextType|null>(null)
