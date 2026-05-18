export interface ApiResponse<T> {
  message?: string
  data: T
}

export interface ApiPaginatedApiResponse<T> {
  message?: string
  data: T[]
  pagination: {
    page: number
    pageSize: number
    totalItems: number
    totalPages: number
    hasNextPage: boolean
    hasPreviousPage: boolean
  }
}

export interface ApiErrorResponse {
  error: {
    code: number
    message: string
    status: number
    timestamp: string
  }
  status: number
  url: string
}

export class ApiError extends Error {
  public readonly status: number
  public readonly code: number
  public readonly timestamp: string
  public readonly message: string
  public readonly url: string

  constructor(response: ApiErrorResponse) {
    super(response.error.message)
    this.name = "ApiError"
    this.status = response.status
    this.code = response.error.code
    this.timestamp = response.error.timestamp
    this.message = response.error.message
    this.url = response.url

    if (Error.captureStackTrace) {
      Error.captureStackTrace(this, ApiError)
    }
  }

  toJSON() {
    return {
      name: this.name,
      message: this.message,
      code: this.code,
      status: this.status,
      timestamp: this.timestamp,
      url: this.url,
    }
  }
}
