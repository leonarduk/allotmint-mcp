package com.allotmint.mcp;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

/** Structured JSON error body returned by {@link GlobalExceptionHandler}. */
record ApiError(int status, String error, String message) {

  static ApiError of(HttpStatus status, String error, String message) {
    return new ApiError(status.value(), error, message);
  }

  ResponseEntity<ApiError> toResponse() {
    return ResponseEntity.status(status).body(this);
  }
}
