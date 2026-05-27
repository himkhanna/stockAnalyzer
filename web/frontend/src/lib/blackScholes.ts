/**
 * Minimal Black-Scholes pricing in the browser. Mirrors the server-side
 * implementation in src/portfolio_intel/options/pricing.py — kept tiny on
 * purpose. Used only by the T+0 payoff overlay; anything authoritative
 * (Greeks, IV solve) still goes through the API.
 */

const SQRT_2PI = Math.sqrt(2 * Math.PI);

function phi(x: number): number {
  return Math.exp(-0.5 * x * x) / SQRT_2PI;
}

// Abramowitz & Stegun erf approximation — accurate to ~1.5e-7.
function erf(x: number): number {
  const sign = x < 0 ? -1 : 1;
  x = Math.abs(x);
  const a1 = 0.254829592,
    a2 = -0.284496736,
    a3 = 1.421413741,
    a4 = -1.453152027,
    a5 = 1.061405429,
    p = 0.3275911;
  const t = 1 / (1 + p * x);
  const y = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-x * x);
  return sign * y;
}

function Phi(x: number): number {
  return 0.5 * (1 + erf(x / Math.SQRT2));
}

export function bsPrice(
  S: number,
  K: number,
  T: number,
  r: number,
  sigma: number,
  right: "call" | "put",
  q = 0,
): number {
  if (T <= 0 || sigma <= 0) {
    return right === "call" ? Math.max(S - K, 0) : Math.max(K - S, 0);
  }
  const sqrtT = Math.sqrt(T);
  const d1 = (Math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrtT);
  const d2 = d1 - sigma * sqrtT;
  const discR = Math.exp(-r * T);
  const discQ = Math.exp(-q * T);
  if (right === "call") return S * discQ * Phi(d1) - K * discR * Phi(d2);
  return K * discR * Phi(-d2) - S * discQ * Phi(-d1);
}

// Re-export for tests if needed.
export const _internal = { phi, erf, Phi };
