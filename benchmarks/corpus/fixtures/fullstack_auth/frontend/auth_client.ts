/**
 * Frontend API client and token session management.
 * Mirrors backend schema and interfaces.
 */

export interface LoginPayload {
  username: string;
  password: string;
}

export interface AuthSession {
  accessToken: string;
  tokenType: string;
  expiresIn: number;
}

export class AuthClient {
  private session: AuthSession | null = null;
  private readonly baseUrl: string;

  constructor(baseUrl: string = "http://api.internal/v1") {
    this.baseUrl = baseUrl;
  }

  async login(payload: LoginPayload): Promise<AuthSession> {
    const res = await fetch(`${this.baseUrl}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      throw new Error(`Login failed with status: ${res.status}`);
    }
    const data = await res.json();
    this.session = {
      accessToken: data.access_token,
      tokenType: data.token_type,
      expiresIn: data.expires_in,
    };
    return this.session;
  }

  async fetchProtectedResource(): Promise<any> {
    if (!this.session) {
      throw new Error("No active session: user must log in first");
    }
    const res = await fetch(`${this.baseUrl}/resource/protected`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${this.session.accessToken}`,
      },
    });
    if (res.status === 403) {
      throw new Error("Permission denied: insufficient role privileges");
    }
    return res.json();
  }

  logout(): void {
    this.session = null;
  }
}

// Negative control: UI geometry calculator with no auth connections
export function calculateElementBounds(width: number, height: number, scale: number) {
  return { width: width * scale, height: height * scale };
}
