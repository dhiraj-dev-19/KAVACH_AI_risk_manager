/**
 * AuthContext.tsx — In-memory JWT token store for JUDGE frontend.
 *
 * Deliberately avoids localStorage/sessionStorage (as required).
 * Token is held in React state and lost on page refresh — this is the
 * correct secure default without persistence.
 */

import React, { createContext, useContext, useState } from 'react';

interface AuthContextValue {
  token: string | null;
  setToken: (t: string | null) => void;
}

const AuthContext = createContext<AuthContextValue>({
  token: null,
  setToken: () => {},
});

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(null);

  return (
    <AuthContext.Provider value={{ token, setToken }}>
      {children}
    </AuthContext.Provider>
  );
};

/** Hook — call anywhere inside <AuthProvider> to get/set the bearer token. */
export const useAuth = (): AuthContextValue => useContext(AuthContext);
