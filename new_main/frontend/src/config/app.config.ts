const getApiBaseUrl = (): string => {
  const env = process.env.NEXT_PUBLIC_API_ENDPOINT
  if (env !== undefined) return env
  return "http://localhost:8000"
}

export const appConfig = {
  api: {
    baseURL: getApiBaseUrl(),
    timeout: 30000,
    NEXT_PUBLIC_GA_MEASUREMENT_ID: process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID,
  },

  app: {
    name: "Exmatch",
    version: "1.0.0",
  },

  features: {
    enableAnalytics: true,
  },
} as const
