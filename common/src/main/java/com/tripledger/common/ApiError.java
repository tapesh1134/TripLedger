package com.tripledger.common;

import org.springframework.http.HttpStatus;

public class ApiError extends RuntimeException {
  public final HttpStatus status;

  public ApiError(HttpStatus status, String message) {
    super(message);
    this.status = status;
  }

  public static ApiError bad(String text) {
    return new ApiError(HttpStatus.BAD_REQUEST, text);
  }

  public static ApiError forbidden() {
    return new ApiError(HttpStatus.FORBIDDEN, "Access denied");
  }

  public static ApiError conflict(String text) {
    return new ApiError(HttpStatus.CONFLICT, text);
  }

  public static ApiError missing() {
    return new ApiError(HttpStatus.NOT_FOUND, "Record not found");
  }
}
