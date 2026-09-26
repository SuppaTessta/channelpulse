/** The API the smoke tests check directly (make smoke passes the local API_PORT). */
export const API = process.env.SMOKE_API_URL ?? "http://127.0.0.1:8000";
