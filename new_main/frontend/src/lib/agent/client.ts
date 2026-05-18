/* eslint-disable @typescript-eslint/no-explicit-any */
import axios, { AxiosError, type AxiosInstance, type AxiosRequestConfig } from "axios"

import { appConfig } from "@/config/app.config"
import { COOKIE_KEYS } from "@/constants/cookies"
import { defaultLocale } from "@/i18n/config"
import { ApiError, ApiPaginatedApiResponse } from "./types"

export interface AgentConfig {
  token?: string
}

function getCurrentLocale(): string {
  if (typeof window === "undefined") return defaultLocale

  const localeCookie = document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${COOKIE_KEYS.LANGUAGE}=`))

  return localeCookie?.split("=")[1] || defaultLocale
}

export class Agent {
  private client: AxiosInstance

  constructor(config?: AgentConfig) {
    this.client = this.createClient(config)
  }

  private createClient(config?: AgentConfig): AxiosInstance {
    const client = axios.create({
      baseURL: appConfig.api.baseURL,
      timeout: appConfig.api.timeout,
      headers: { "Content-Type": "application/json" },
    })

    client.interceptors.request.use(async (requestConfig) => {
      if (config?.token) {
        requestConfig.headers.Authorization = config.token
      }
      const locale = getCurrentLocale()
      requestConfig.headers["Accept-Language"] = locale
      requestConfig.headers["locale"] = locale
      return requestConfig
    })

    client.interceptors.response.use(
      (res) => res,
      (error: AxiosError<any>) => {
        if (error instanceof ApiError) throw error

        const response = error.response
        const data = response?.data

        if (response) {
          throw new ApiError({
            error: {
              code: data?.code ?? response.status,
              message: data?.message ?? response.statusText ?? "Request failed",
              status: response.status,
              timestamp: data?.timestamp ?? new Date().toISOString(),
            },
            status: response.status,
            url: error.config?.url ?? "",
          })
        }

        throw new ApiError({
          error: {
            code: 0,
            message: "Network error - Please check your connection",
            status: 0,
            timestamp: new Date().toISOString(),
          },
          status: 0,
          url: error.config?.url ?? "",
        })
      }
    )

    return client
  }

  async get<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> {
    const res = await this.client.get<T>(url, config)
    return res.data
  }

  async getPaginated<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<ApiPaginatedApiResponse<T>> {
    const res = await this.client.get<ApiPaginatedApiResponse<T>>(url, config)
    return res.data
  }

  async post<T = unknown, D = unknown>(url: string, data?: D, config?: AxiosRequestConfig): Promise<T> {
    const res = await this.client.post<T>(url, data, config)
    return res.data
  }

  async put<T = unknown, D = unknown>(url: string, data?: D, config?: AxiosRequestConfig): Promise<T> {
    const res = await this.client.put<T>(url, data, config)
    return res.data
  }

  async patch<T = unknown, D = unknown>(url: string, data?: D, config?: AxiosRequestConfig): Promise<T> {
    const res = await this.client.patch<T>(url, data, config)
    return res.data
  }

  async delete<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> {
    const res = await this.client.delete<T>(url, config)
    return res.data
  }
}

export const agent = new Agent()
